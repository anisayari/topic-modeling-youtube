# YouTube Topic Modeling

> **Work in Progress** - This project is under active development. Some features may be incomplete or subject to change.

A Flask application to extract YouTube comments and perform topic modeling analysis.

## Features

### 1. Comment Extraction
- Search YouTube channels by handle (`@channelname`) or ID
- Display video count
- **Parallel extraction** of all comments from all videos (5 concurrent workers)
- Save to JSON format

### 2. Data Insights
- View all extracted data files
- Channel statistics (videos, comments, replies)
- Comments per video chart
- Comments timeline visualization
- Video list sorted by engagement

### 3. Topic Modeling (Coming Soon)
Pipeline for topic modeling:
1. **Data Loading** - Select JSON file
2. **Preprocessing** - Text cleaning (lowercase, stopwords, lemmatization)
3. **Vectorization** - Transform to numerical vectors
4. **Topic Modeling** - Available algorithms:
   - LDA (Latent Dirichlet Allocation)
   - NMF (Non-negative Matrix Factorization)
   - BERTopic
   - Top2Vec
5. **Dimensionality Reduction** - UMAP, t-SNE, PCA

## Installation

```bash
# Clone the repository
git clone https://github.com/YOUR_USERNAME/topic-modeling-youtube.git
cd topic-modeling-youtube

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

## Usage

```bash
python app.py
```

Open http://localhost:4242

To use a different port:
```bash
python app.py --port 8080
```

## Project Structure

```
youtube-comments-scraper/
├── app.py              # Flask application
├── requirements.txt    # Python dependencies
├── README.md           # Documentation
├── templates/
│   └── index.html      # Web interface
└── data/               # Generated JSON files
```

## Extracted Data Format

```json
{
  "channel_name": "ChannelName",
  "scraped_at": "2025-12-22T15:30:00",
  "total_videos": 150,
  "total_comments": 25000,
  "videos": [
    {
      "video_id": "abc123",
      "title": "Video Title",
      "url": "https://www.youtube.com/watch?v=abc123",
      "comment_count": 500,
      "comments": [
        {
          "author": "User1",
          "author_id": "UC...",
          "text": "Great video!",
          "likes": 42,
          "timestamp": 1703257800,
          "parent": "root",
          "is_reply": false
        }
      ]
    }
  ]
}
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Web interface |
| `/api/channel-info` | POST | Get channel info |
| `/api/scrape-comments` | POST | Extract comments (parallel) |
| `/api/files` | GET | List JSON files |
| `/api/files-stats` | GET | List files with statistics |
| `/api/file-detail/<filename>` | GET | Get file content |
| `/api/download/<filename>` | GET | Download a file |

## Tech Stack

- **Backend**: Flask, yt-dlp
- **Frontend**: HTML/CSS/JavaScript, Plotly.js
- **Topic Modeling** (planned): scikit-learn, BERTopic, Gensim
- **NLP** (planned): spaCy, NLTK
- **Dimensionality Reduction** (planned): UMAP, t-SNE

## Roadmap

- [x] YouTube comment extraction
- [x] Parallel extraction (5 workers)
- [x] Web interface with tabs
- [x] Data insights dashboard
- [ ] NLP preprocessing pipeline
- [ ] LDA/NMF implementation
- [ ] BERTopic integration
- [ ] Interactive visualization
- [ ] Results export

## License

MIT
