import os
import json
import subprocess
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_file
import yt_dlp

app = Flask(__name__)
app.config['OUTPUT_DIR'] = 'output'

# Créer le dossier output s'il n'existe pas
os.makedirs(app.config['OUTPUT_DIR'], exist_ok=True)


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
    """Récupère tous les commentaires d'une vidéo."""
    ydl_opts = {
        'quiet': True,
        'skip_download': True,
        'getcomments': True,
        'extractor_args': {'youtube': {'comment_sort': ['top']}},
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


@app.route('/api/scrape-comments', methods=['POST'])
def scrape_comments():
    """Endpoint pour scraper tous les commentaires d'une chaîne."""
    data = request.json
    channel_input = data.get('channel', '')

    if not channel_input:
        return jsonify({'error': 'Veuillez fournir un nom ou ID de chaîne'}), 400

    try:
        videos, channel_name = get_channel_videos(channel_input)

        all_comments = {
            'channel_name': channel_name,
            'scraped_at': datetime.now().isoformat(),
            'total_videos': len(videos),
            'videos': []
        }

        for i, video in enumerate(videos):
            print(f"Scraping comments for video {i+1}/{len(videos)}: {video['title']}")
            try:
                comments = get_video_comments(video['url'])
                all_comments['videos'].append({
                    'video_id': video['id'],
                    'title': video['title'],
                    'url': video['url'],
                    'comment_count': len(comments),
                    'comments': comments
                })
            except Exception as e:
                print(f"Error scraping {video['title']}: {e}")
                all_comments['videos'].append({
                    'video_id': video['id'],
                    'title': video['title'],
                    'url': video['url'],
                    'error': str(e),
                    'comments': []
                })

        # Calculer le total de commentaires
        total_comments = sum(v.get('comment_count', 0) for v in all_comments['videos'])
        all_comments['total_comments'] = total_comments

        # Sauvegarder en JSON
        safe_channel_name = "".join(c for c in channel_name if c.isalnum() or c in (' ', '-', '_')).strip()
        filename = f"{safe_channel_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        filepath = os.path.join(app.config['OUTPUT_DIR'], filename)

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(all_comments, f, ensure_ascii=False, indent=2)

        return jsonify({
            'success': True,
            'channel_name': channel_name,
            'total_videos': len(videos),
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


if __name__ == '__main__':
    app.run(debug=True, port=5000)
