import os
import json
import argparse
import threading
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, render_template, request, jsonify, send_file
import yt_dlp

# Number of parallel workers for comment extraction
MAX_WORKERS = 5

app = Flask(__name__)
app.config['OUTPUT_DIR'] = 'data'

# Créer le dossier data s'il n'existe pas
os.makedirs(app.config['OUTPUT_DIR'], exist_ok=True)


def get_already_downloaded_video_ids():
    """Get all video IDs that have already been downloaded from existing JSON files."""
    downloaded_ids = set()
    output_dir = app.config['OUTPUT_DIR']
    
    if os.path.exists(output_dir):
        for filename in os.listdir(output_dir):
            if filename.endswith('.json'):
                filepath = os.path.join(output_dir, filename)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        for video in data.get('videos', []):
                            if video.get('video_id'):
                                downloaded_ids.add(video['video_id'])
                except Exception:
                    pass
    
    return downloaded_ids


def get_channel_videos(channel_url):
    """Récupère la liste de toutes les vidéos d'une chaîne."""
    ydl_opts = {
        'quiet': True,
        'extract_flat': True,
        'force_generic_extractor': False,
    }

    # Construire l'URL de la chaîne si ce n'est pas déjà une URL complète
    if not channel_url.startswith('http'):
        if channel_url.startswith('@'):
            channel_url = f'https://www.youtube.com/{channel_url}/videos'
        else:
            channel_url = f'https://www.youtube.com/channel/{channel_url}/videos'
    elif '/videos' not in channel_url:
        channel_url = channel_url.rstrip('/') + '/videos'

    videos = []
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        result = ydl.extract_info(channel_url, download=False)

        if result and 'entries' in result:
            for entry in result['entries']:
                if entry:
                    videos.append({
                        'id': entry.get('id'),
                        'title': entry.get('title'),
                        'url': f"https://www.youtube.com/watch?v={entry.get('id')}"
                    })

    return videos, result.get('channel', result.get('uploader', 'Unknown'))


def get_video_comments(video_url):
    """Fetch all comments from a video."""
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'getcomments': True,
        'extract_flat': False,
        'extractor_args': {'youtube': {'comment_sort': ['top'], 'skip': ['dash', 'hls']}},
    }

    comments = []
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        result = ydl.extract_info(video_url, download=False)

        if result and 'comments' in result:
            for comment in result['comments']:
                comments.append({
                    'author': comment.get('author'),
                    'author_id': comment.get('author_id'),
                    'text': comment.get('text'),
                    'likes': comment.get('like_count', 0),
                    'timestamp': comment.get('timestamp'),
                    'parent': comment.get('parent', 'root'),
                    'is_reply': comment.get('parent') != 'root'
                })

    return comments


def scrape_video_comments(video):
    """Helper function to scrape comments from a single video (for parallel execution)."""
    try:
        comments = get_video_comments(video['url'])
        return {
            'video_id': video['id'],
            'title': video['title'],
            'url': video['url'],
            'comment_count': len(comments),
            'comments': comments,
            'error': None
        }
    except Exception as e:
        return {
            'video_id': video['id'],
            'title': video['title'],
            'url': video['url'],
            'comment_count': 0,
            'comments': [],
            'error': str(e)
        }


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/channel-info', methods=['POST'])
def get_channel_info():
    """Endpoint pour récupérer les infos de la chaîne."""
    data = request.json
    channel_input = data.get('channel', '')

    if not channel_input:
        return jsonify({'error': 'Veuillez fournir un nom ou ID de chaîne'}), 400

    try:
        videos, channel_name = get_channel_videos(channel_input)
        return jsonify({
            'channel_name': channel_name,
            'video_count': len(videos),
            'videos': videos
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def save_progress(filepath, data, lock):
    """Save current progress to JSON file (thread-safe)."""
    with lock:
        # Update total comments before saving
        data['total_comments'] = sum(v.get('comment_count', 0) for v in data['videos'])
        data['videos_completed'] = len(data['videos'])
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


@app.route('/api/scrape-comments', methods=['POST'])
def scrape_comments():
    """Endpoint to scrape all comments from a channel (parallelized with progressive save)."""
    data = request.json
    channel_input = data.get('channel', '')
    limit = data.get('limit')  # None means no limit
    skip_existing = data.get('skip_existing', False)

    if not channel_input:
        return jsonify({'error': 'Please provide a channel name or ID'}), 400

    try:
        videos, channel_name = get_channel_videos(channel_input)
        total_available = len(videos)
        skipped_count = 0

        # Filter out already downloaded videos if skip_existing is enabled
        if skip_existing:
            already_downloaded = get_already_downloaded_video_ids()
            original_count = len(videos)
            videos = [v for v in videos if v['id'] not in already_downloaded]
            skipped_count = original_count - len(videos)
            print(f"Skipping {skipped_count} already downloaded videos")

        # Apply limit if specified
        if limit and limit > 0:
            videos = videos[:limit]

        # Prepare filename early for progressive saving
        safe_channel_name = "".join(c for c in channel_name if c.isalnum() or c in (' ', '-', '_')).strip()
        filename = f"{safe_channel_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        filepath = os.path.join(app.config['OUTPUT_DIR'], filename)

        all_comments = {
            'channel_name': channel_name,
            'scraped_at': datetime.now().isoformat(),
            'total_videos': len(videos),
            'videos_completed': 0,
            'total_comments': 0,
            'videos': []
        }

        # Lock for thread-safe file writing
        file_lock = threading.Lock()

        # Save initial empty file
        save_progress(filepath, all_comments, file_lock)

        print(f"Starting parallel extraction for {len(videos)} videos with {MAX_WORKERS} workers...")
        print(f"Progress will be saved to: {filename}")

        # Parallel extraction using ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            # Submit all tasks
            future_to_video = {executor.submit(scrape_video_comments, video): video for video in videos}

            completed = 0
            for future in as_completed(future_to_video):
                completed += 1
                result = future.result()
                video_title = result['title'][:50] if result['title'] else 'Unknown'

                if result['error']:
                    print(f"[{completed}/{len(videos)}] Error: {video_title} - {result['error']}")
                else:
                    print(f"[{completed}/{len(videos)}] Done: {video_title} ({result['comment_count']} comments)")

                # Add result and save progress
                with file_lock:
                    all_comments['videos'].append(result)
                save_progress(filepath, all_comments, file_lock)

        # Final stats
        total_comments = sum(v.get('comment_count', 0) for v in all_comments['videos'])

        print(f"Extraction complete! {total_comments} comments saved to {filename}")

        return jsonify({
            'success': True,
            'channel_name': channel_name,
            'total_videos': len(videos),
            'total_available': total_available,
            'skipped_existing': skipped_count,
            'total_comments': total_comments,
            'filename': filename,
            'filepath': filepath
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/download/<filename>')
def download_file(filename):
    """Télécharger le fichier JSON généré."""
    filepath = os.path.join(app.config['OUTPUT_DIR'], filename)
    if os.path.exists(filepath):
        return send_file(filepath, as_attachment=True)
    return jsonify({'error': 'Fichier non trouvé'}), 404


@app.route('/api/files')
def list_files():
    """Lister tous les fichiers JSON disponibles."""
    files = []
    output_dir = app.config['OUTPUT_DIR']

    if os.path.exists(output_dir):
        for filename in os.listdir(output_dir):
            if filename.endswith('.json'):
                filepath = os.path.join(output_dir, filename)
                size = os.path.getsize(filepath)
                # Formater la taille
                if size < 1024:
                    size_str = f"{size} B"
                elif size < 1024 * 1024:
                    size_str = f"{size / 1024:.1f} KB"
                else:
                    size_str = f"{size / (1024 * 1024):.1f} MB"

                files.append({
                    'name': filename,
                    'size': size_str,
                    'path': filepath
                })

    # Trier par date de modification (plus récent en premier)
    files.sort(key=lambda x: os.path.getmtime(x['path']), reverse=True)

    return jsonify({'files': files})


@app.route('/api/files-stats')
def list_files_with_stats():
    """Lister tous les fichiers JSON avec leurs statistiques."""
    files = []
    output_dir = app.config['OUTPUT_DIR']
    total_videos = 0
    total_comments = 0
    channels = set()

    if os.path.exists(output_dir):
        for filename in os.listdir(output_dir):
            if filename.endswith('.json'):
                filepath = os.path.join(output_dir, filename)
                size = os.path.getsize(filepath)

                # Formater la taille
                if size < 1024:
                    size_str = f"{size} B"
                elif size < 1024 * 1024:
                    size_str = f"{size / 1024:.1f} KB"
                else:
                    size_str = f"{size / (1024 * 1024):.1f} MB"

                file_info = {
                    'name': filename,
                    'size': size_str,
                    'path': filepath
                }

                # Lire les métadonnées du fichier JSON
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        file_info['channel_name'] = data.get('channel_name', '')
                        file_info['video_count'] = data.get('total_videos', 0)
                        file_info['comment_count'] = data.get('total_comments', 0)
                        file_info['scraped_at'] = data.get('scraped_at', '')

                        # Accumuler les stats globales
                        if file_info['channel_name']:
                            channels.add(file_info['channel_name'])
                        total_videos += file_info['video_count']
                        total_comments += file_info['comment_count']
                except Exception:
                    pass

                files.append(file_info)

    # Trier par date de scraping (plus récent en premier)
    files.sort(key=lambda x: x.get('scraped_at', ''), reverse=True)

    return jsonify({
        'files': files,
        'total_channels': len(channels),
        'total_videos': total_videos,
        'total_comments': total_comments
    })


@app.route('/api/file-detail/<filename>')
def get_file_detail(filename):
    """Récupérer le contenu détaillé d'un fichier JSON."""
    filepath = os.path.join(app.config['OUTPUT_DIR'], filename)

    if not os.path.exists(filepath):
        return jsonify({'error': 'Fichier non trouvé'}), 404

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='YouTube Comments Scraper')
    parser.add_argument('--port', type=int, default=4242, help='Port to run the server on (default: 4242)')
    parser.add_argument('--host', type=str, default='127.0.0.1', help='Host to run the server on (default: 127.0.0.1)')
    args = parser.parse_args()

    app.run(debug=True, host=args.host, port=args.port)
