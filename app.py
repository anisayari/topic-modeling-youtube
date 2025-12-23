import os
import json
import argparse
import threading
import uuid
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Queue
from flask import Flask, render_template, request, jsonify, send_file
import yt_dlp

# Number of parallel workers for comment extraction (default to CPU count)
DEFAULT_WORKERS = os.cpu_count() or 4
MAX_WORKERS = DEFAULT_WORKERS * 2  # Allow up to 2x CPU count

app = Flask(__name__)
app.config['OUTPUT_DIR'] = 'data'

# Créer le dossier data s'il n'existe pas
os.makedirs(app.config['OUTPUT_DIR'], exist_ok=True)

# Global state for extraction tracking
extraction_state = {
    'active': False,
    'stop_requested': False,
    'current_channel': None,
    'current_video': None,
    'videos_total': 0,
    'videos_completed': 0,
    'comments_extracted': 0,
    'filename': None
}
extraction_lock = threading.Lock()

# Queue for multi-channel extraction
extraction_queue = Queue()
queue_list = []  # For display purposes
queue_lock = threading.Lock()


def get_already_downloaded_video_ids(channel_folder=None):
    """Get all video IDs that have already been downloaded.

    If channel_folder is provided, only check that channel's videos folder.
    Otherwise, check all channels.
    """
    downloaded_ids = set()
    output_dir = app.config['OUTPUT_DIR']

    if channel_folder:
        # Check specific channel's videos folder
        videos_dir = os.path.join(output_dir, channel_folder, 'videos')
        if os.path.exists(videos_dir):
            for filename in os.listdir(videos_dir):
                if filename.endswith('.json'):
                    video_id = filename.replace('.json', '')
                    downloaded_ids.add(video_id)
    else:
        # Check all channels
        if os.path.exists(output_dir):
            for channel_name in os.listdir(output_dir):
                videos_dir = os.path.join(output_dir, channel_name, 'videos')
                if os.path.isdir(videos_dir):
                    for filename in os.listdir(videos_dir):
                        if filename.endswith('.json'):
                            video_id = filename.replace('.json', '')
                            downloaded_ids.add(video_id)

    return downloaded_ids


def get_channel_videos(channel_url):
    """Récupère la liste de toutes les vidéos d'une chaîne avec métadonnées."""
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': True,
        'force_generic_extractor': False,
    }

    # Construire l'URL de la chaîne si ce n'est pas déjà une URL complète
    original_input = channel_url
    if not channel_url.startswith('http'):
        if channel_url.startswith('@'):
            channel_url = f'https://www.youtube.com/{channel_url}/videos'
        else:
            channel_url = f'https://www.youtube.com/channel/{channel_url}/videos'
    elif '/videos' not in channel_url:
        channel_url = channel_url.rstrip('/') + '/videos'

    videos = []
    channel_info = {}

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        result = ydl.extract_info(channel_url, download=False)

        if result:
            # Extract channel metadata
            channel_info = {
                'channel_name': result.get('channel', result.get('uploader', 'Unknown')),
                'channel_id': result.get('channel_id', result.get('uploader_id', '')),
                'channel_url': result.get('channel_url', result.get('uploader_url', '')),
                'description': result.get('description', ''),
                'subscriber_count': result.get('channel_follower_count'),
                'original_input': original_input,
            }

            if 'entries' in result:
                for entry in result['entries']:
                    if entry:
                        videos.append({
                            'id': entry.get('id'),
                            'title': entry.get('title'),
                            'url': f"https://www.youtube.com/watch?v={entry.get('id')}"
                        })

    return videos, channel_info


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


@app.route('/api/system-info')
def system_info():
    """Get system info for UI configuration."""
    return jsonify({
        'cpu_count': os.cpu_count() or 4,
        'default_workers': DEFAULT_WORKERS,
        'max_workers': MAX_WORKERS
    })


@app.route('/api/channel-info', methods=['POST'])
def get_channel_info():
    """Endpoint pour récupérer les infos de la chaîne."""
    data = request.json
    channel_input = data.get('channel', '')

    if not channel_input:
        return jsonify({'error': 'Veuillez fournir un nom ou ID de chaîne'}), 400

    try:
        videos, channel_info = get_channel_videos(channel_input)
        return jsonify({
            'channel_name': channel_info.get('channel_name', 'Unknown'),
            'channel_id': channel_info.get('channel_id', ''),
            'description': channel_info.get('description', ''),
            'subscriber_count': channel_info.get('subscriber_count'),
            'video_count': len(videos),
            'videos': videos
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def save_progress(filepath, data, lock):
    """Save current progress to JSON file (thread-safe)."""
    with lock:
        # Update stats before saving
        data['total_comments'] = sum(v.get('comment_count', 0) for v in data['videos'])
        data['total_videos'] = len(data['videos'])
        data['videos_completed'] = len(data['videos'])
        data['last_updated'] = datetime.now().isoformat()
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


def update_extraction_state(**kwargs):
    """Update global extraction state."""
    with extraction_lock:
        extraction_state.update(kwargs)


def reset_extraction_state():
    """Reset extraction state."""
    with extraction_lock:
        extraction_state.update({
            'active': False,
            'stop_requested': False,
            'current_channel': None,
            'current_video': None,
            'videos_total': 0,
            'videos_completed': 0,
            'comments_extracted': 0,
            'filename': None
        })


def save_video_json(videos_dir, video_data, lock):
    """Save a single video's data to its own JSON file."""
    video_id = video_data.get('video_id')
    if not video_id:
        return
    filepath = os.path.join(videos_dir, f"{video_id}.json")
    with lock:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(video_data, f, ensure_ascii=False, indent=2)


def save_channel_info(channel_dir, channel_info, videos_stats, lock):
    """Save/update channel info.json with current stats."""
    filepath = os.path.join(channel_dir, 'info.json')
    with lock:
        info = channel_info.copy()
        info['last_updated'] = datetime.now().isoformat()
        info['total_videos'] = videos_stats.get('total_videos', 0)
        info['videos_extracted'] = videos_stats.get('videos_extracted', 0)
        info['total_comments'] = videos_stats.get('total_comments', 0)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(info, f, ensure_ascii=False, indent=2)


def do_extraction(channel_input, limit=None, skip_existing=False, workers=None):
    """Worker function for extraction (runs in background thread).

    New folder structure:
    data/
      @ChannelName/
        info.json              <- Channel metadata
        videos/
          <video_id>.json      <- One file per video
    """
    try:
        update_extraction_state(active=True, stop_requested=False)

        videos, channel_info = get_channel_videos(channel_input)
        channel_name = channel_info.get('channel_name', 'Unknown')
        total_available = len(videos)

        update_extraction_state(current_channel=channel_name)

        # Create safe folder name from channel input or name
        if channel_input.startswith('@'):
            folder_name = channel_input  # Use @handle as folder name
        else:
            folder_name = "".join(c for c in channel_name if c.isalnum() or c in (' ', '-', '_', '@')).strip()

        # Create folder structure
        channel_dir = os.path.join(app.config['OUTPUT_DIR'], folder_name)
        videos_dir = os.path.join(channel_dir, 'videos')
        os.makedirs(videos_dir, exist_ok=True)

        update_extraction_state(filename=folder_name)

        # Get already downloaded video IDs for this channel
        already_downloaded = get_already_downloaded_video_ids(folder_name)
        existing_count = len(already_downloaded)

        # Filter out already downloaded videos if skip_existing is enabled
        if skip_existing:
            original_count = len(videos)
            videos = [v for v in videos if v['id'] not in already_downloaded]
            skipped_count = original_count - len(videos)
            if skipped_count > 0:
                print(f"Skipping {skipped_count} already downloaded videos")

        # Apply limit if specified
        if limit and limit > 0:
            videos = videos[:limit]

        if len(videos) == 0:
            print("All videos already extracted, nothing new to do")
            reset_extraction_state()
            return {
                'success': True,
                'channel_name': channel_name,
                'folder': folder_name,
                'total_videos': existing_count,
                'message': 'All videos already extracted'
            }

        # Lock for thread-safe file writing
        file_lock = threading.Lock()

        # Calculate existing comments count
        existing_comments = 0
        for vid_file in os.listdir(videos_dir) if os.path.exists(videos_dir) else []:
            if vid_file.endswith('.json'):
                try:
                    with open(os.path.join(videos_dir, vid_file), 'r') as f:
                        vid_data = json.load(f)
                        existing_comments += vid_data.get('comment_count', 0)
                except Exception:
                    pass

        update_extraction_state(
            videos_total=len(videos),
            videos_completed=0,
            comments_extracted=existing_comments
        )

        # Save initial channel info
        videos_stats = {
            'total_videos': total_available,
            'videos_extracted': existing_count,
            'total_comments': existing_comments
        }
        save_channel_info(channel_dir, channel_info, videos_stats, file_lock)

        num_workers = min(workers or DEFAULT_WORKERS, MAX_WORKERS)
        print(f"Starting parallel extraction for {len(videos)} NEW videos with {num_workers} workers...")
        print(f"Saving to: {channel_dir}/videos/")

        total_comments = existing_comments
        completed = 0

        # Parallel extraction using ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            future_to_video = {executor.submit(scrape_video_comments, video): video for video in videos}

            rate_limit_hit = False
            successful_videos = 0

            for future in as_completed(future_to_video):
                # Check if stop was requested
                if extraction_state['stop_requested']:
                    print("Stop requested, cancelling remaining tasks...")
                    executor.shutdown(wait=False, cancel_futures=True)
                    break

                completed += 1
                result = future.result()
                video_title = result['title'][:50] if result['title'] else 'Unknown'

                if result.get('error'):
                    error_msg = result['error']
                    print(f"[{completed}/{len(videos)}] Error: {video_title} - {error_msg}")

                    # Check for rate limiting (403 Forbidden)
                    if '403' in error_msg or 'Forbidden' in error_msg:
                        print("\n⚠️  RATE LIMIT DETECTED (403 Forbidden)")
                        print("YouTube is blocking requests. Stopping extraction...")
                        rate_limit_hit = True
                        executor.shutdown(wait=False, cancel_futures=True)
                        break

                    # Don't save videos with errors
                    continue

                print(f"[{completed}/{len(videos)}] Done: {video_title} ({result['comment_count']} comments)")

                # Save individual video file (only successful ones)
                save_video_json(videos_dir, result, file_lock)
                successful_videos += 1

                # Update stats
                total_comments += result.get('comment_count', 0)
                videos_stats = {
                    'total_videos': total_available,
                    'videos_extracted': existing_count + successful_videos,
                    'total_comments': total_comments
                }
                save_channel_info(channel_dir, channel_info, videos_stats, file_lock)

                # Update global state
                update_extraction_state(
                    videos_completed=completed,
                    current_video=video_title,
                    comments_extracted=total_comments
                )

        # Final stats
        was_stopped = extraction_state['stop_requested']
        final_video_count = existing_count + successful_videos

        if rate_limit_hit:
            print(f"\n⚠️  Extraction stopped due to rate limiting!")
            print(f"Successfully extracted {successful_videos} videos before hitting the limit.")
            print(f"Re-run with 'Skip already downloaded' to continue later.")
        elif was_stopped:
            print(f"Extraction stopped! {total_comments} comments saved to {folder_name}/")
        else:
            print(f"Extraction complete! {total_comments} comments in {final_video_count} videos saved to {folder_name}/")

        reset_extraction_state()

        return {
            'success': not rate_limit_hit,
            'channel_name': channel_name,
            'folder': folder_name,
            'total_videos': final_video_count,
            'total_comments': total_comments,
            'stopped': was_stopped,
            'rate_limited': rate_limit_hit,
            'message': 'Rate limit hit (403). Try again later with fewer workers.' if rate_limit_hit else None
        }
    except Exception as e:
        print(f"Extraction error: {e}")
        reset_extraction_state()
        return {'error': str(e)}


def queue_worker():
    """Background worker to process extraction queue."""
    while True:
        job = extraction_queue.get()
        if job is None:
            break
        
        job_id, channel_input, limit, skip_existing, workers = job

        # Update queue status
        with queue_lock:
            for item in queue_list:
                if item['id'] == job_id:
                    item['status'] = 'running'
                    break

        # Do the extraction
        result = do_extraction(channel_input, limit, skip_existing, workers)
        
        # Update queue status
        with queue_lock:
            for item in queue_list:
                if item['id'] == job_id:
                    item['status'] = 'completed' if result.get('success') else 'error'
                    item['result'] = result
                    break
        
        extraction_queue.task_done()


# Start the queue worker thread
queue_thread = threading.Thread(target=queue_worker, daemon=True)
queue_thread.start()


@app.route('/api/scrape-comments', methods=['POST'])
def scrape_comments():
    """Endpoint to queue channel extraction(s). Supports multiple channels separated by commas."""
    data = request.json
    channel_input = data.get('channel', '')
    limit = data.get('limit')
    skip_existing = data.get('skip_existing', False)
    workers = data.get('workers', DEFAULT_WORKERS)

    if not channel_input:
        return jsonify({'error': 'Please provide a channel name or ID'}), 400

    # Parse multiple channels (comma-separated)
    channels = [ch.strip() for ch in channel_input.split(',') if ch.strip()]

    if not channels:
        return jsonify({'error': 'Please provide at least one valid channel'}), 400

    job_ids = []
    for channel in channels:
        # Create job for each channel
        job_id = str(uuid.uuid4())[:8]
        job = (job_id, channel, limit, skip_existing, workers)

        # Add to queue
        with queue_lock:
            queue_list.append({
                'id': job_id,
                'channel': channel,
                'status': 'queued',
                'result': None
            })

        extraction_queue.put(job)
        job_ids.append(job_id)

    return jsonify({
        'success': True,
        'job_ids': job_ids,
        'channels_queued': len(channels),
        'message': f'{len(channels)} channel(s) queued for extraction',
        'queue_size': extraction_queue.qsize()
    })


@app.route('/api/extraction-status')
def get_extraction_status():
    """Get current extraction status for real-time progress."""
    with extraction_lock:
        status = extraction_state.copy()
    
    with queue_lock:
        status['queue'] = queue_list.copy()
    
    return jsonify(status)


@app.route('/api/stop-extraction', methods=['POST'])
def stop_extraction():
    """Stop the current extraction."""
    with extraction_lock:
        if extraction_state['active']:
            extraction_state['stop_requested'] = True
            return jsonify({'success': True, 'message': 'Stop requested'})
        else:
            return jsonify({'success': False, 'message': 'No extraction in progress'})


@app.route('/api/clear-queue', methods=['POST'])
def clear_queue():
    """Clear completed/errored items from queue."""
    with queue_lock:
        queue_list[:] = [item for item in queue_list if item['status'] in ('queued', 'running')]
    return jsonify({'success': True})


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
    """List all channels with their statistics (new folder structure)."""
    channels_list = []
    output_dir = app.config['OUTPUT_DIR']
    total_videos = 0
    total_comments = 0

    if os.path.exists(output_dir):
        for folder_name in os.listdir(output_dir):
            channel_dir = os.path.join(output_dir, folder_name)
            info_path = os.path.join(channel_dir, 'info.json')

            # Skip if not a directory or no info.json
            if not os.path.isdir(channel_dir):
                continue

            channel_info = {
                'folder': folder_name,
                'channel_name': folder_name,
                'video_count': 0,
                'comment_count': 0,
                'subscriber_count': None,
                'last_updated': '',
                'size': '0 B'
            }

            # Read info.json if exists
            if os.path.exists(info_path):
                try:
                    with open(info_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        channel_info['channel_name'] = data.get('channel_name', folder_name)
                        channel_info['channel_id'] = data.get('channel_id', '')
                        channel_info['description'] = data.get('description', '')
                        channel_info['subscriber_count'] = data.get('subscriber_count')
                        channel_info['video_count'] = data.get('videos_extracted', 0)
                        channel_info['total_videos_available'] = data.get('total_videos', 0)
                        channel_info['comment_count'] = data.get('total_comments', 0)
                        channel_info['last_updated'] = data.get('last_updated', '')
                except Exception:
                    pass

            # Calculate folder size
            videos_dir = os.path.join(channel_dir, 'videos')
            folder_size = 0
            if os.path.exists(videos_dir):
                for f in os.listdir(videos_dir):
                    fp = os.path.join(videos_dir, f)
                    if os.path.isfile(fp):
                        folder_size += os.path.getsize(fp)
            if os.path.exists(info_path):
                folder_size += os.path.getsize(info_path)

            if folder_size < 1024:
                channel_info['size'] = f"{folder_size} B"
            elif folder_size < 1024 * 1024:
                channel_info['size'] = f"{folder_size / 1024:.1f} KB"
            else:
                channel_info['size'] = f"{folder_size / (1024 * 1024):.1f} MB"

            # Accumulate global stats
            total_videos += channel_info['video_count']
            total_comments += channel_info['comment_count']

            channels_list.append(channel_info)

    # Sort by last updated (most recent first)
    channels_list.sort(key=lambda x: x.get('last_updated', ''), reverse=True)

    return jsonify({
        'files': channels_list,  # Keep 'files' key for frontend compatibility
        'total_channels': len(channels_list),
        'total_videos': total_videos,
        'total_comments': total_comments
    })


@app.route('/api/file-detail/<folder>')
def get_file_detail(folder):
    """Get detailed content for a channel folder (new structure)."""
    channel_dir = os.path.join(app.config['OUTPUT_DIR'], folder)
    info_path = os.path.join(channel_dir, 'info.json')
    videos_dir = os.path.join(channel_dir, 'videos')

    if not os.path.exists(channel_dir):
        return jsonify({'error': 'Channel folder not found'}), 404

    try:
        # Load channel info
        channel_info = {}
        if os.path.exists(info_path):
            with open(info_path, 'r', encoding='utf-8') as f:
                channel_info = json.load(f)

        # Load all videos
        videos = []
        total_comments = 0
        if os.path.exists(videos_dir):
            for video_file in os.listdir(videos_dir):
                if video_file.endswith('.json'):
                    video_path = os.path.join(videos_dir, video_file)
                    try:
                        with open(video_path, 'r', encoding='utf-8') as f:
                            video_data = json.load(f)
                            videos.append(video_data)
                            total_comments += video_data.get('comment_count', 0)
                    except Exception:
                        pass

        # Build response matching old format for frontend compatibility
        result = {
            'channel_name': channel_info.get('channel_name', folder),
            'channel_id': channel_info.get('channel_id', ''),
            'description': channel_info.get('description', ''),
            'subscriber_count': channel_info.get('subscriber_count'),
            'last_updated': channel_info.get('last_updated', ''),
            'total_videos': len(videos),
            'total_comments': total_comments,
            'videos': videos
        }

        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='YouTube Comments Scraper')
    parser.add_argument('--port', type=int, default=4242, help='Port to run the server on (default: 4242)')
    parser.add_argument('--host', type=str, default='127.0.0.1', help='Host to run the server on (default: 127.0.0.1)')
    args = parser.parse_args()

    app.run(debug=True, host=args.host, port=args.port)
