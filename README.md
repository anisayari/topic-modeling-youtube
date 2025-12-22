# YouTube Topic Modeling

Application Flask pour extraire les commentaires YouTube et effectuer du topic modeling.

## Fonctionnalites

### 1. Extraction des commentaires
- Recherche de chaine YouTube par nom (`@nomchaine`) ou ID
- Affichage du nombre de videos
- Extraction de tous les commentaires de toutes les videos
- Sauvegarde en JSON

### 2. Modelisation (en construction)
Pipeline de topic modeling :
1. **Chargement des donnees** - Selection du fichier JSON
2. **Pre-traitement** - Nettoyage du texte (minuscules, stopwords, lemmatisation)
3. **Vectorisation** - Transformation en vecteurs numeriques
4. **Topic Modeling** - Algorithmes disponibles :
   - LDA (Latent Dirichlet Allocation)
   - NMF (Non-negative Matrix Factorization)
   - BERTopic
   - Top2Vec
5. **Reduction dimensionnelle** - UMAP, t-SNE, PCA

### 3. Visualisation (en construction)
- Graphique 3D interactif (Plotly)
- Coloration par topic, sentiment, video ou date
- Taille des points configurable

## Installation

```bash
cd youtube-comments-scraper
pip install -r requirements.txt
```

## Lancement

```bash
python app.py
```

Puis ouvrir http://localhost:5000

## Structure du projet

```
youtube-comments-scraper/
├── app.py              # Application Flask
├── requirements.txt    # Dependances Python
├── README.md           # Documentation
├── templates/
│   └── index.html      # Interface web
└── output/             # Fichiers JSON generes
```

## Format des donnees extraites

```json
{
  "channel_name": "NomChaine",
  "scraped_at": "2025-12-22T15:30:00",
  "total_videos": 150,
  "total_comments": 25000,
  "videos": [
    {
      "video_id": "abc123",
      "title": "Titre de la video",
      "url": "https://www.youtube.com/watch?v=abc123",
      "comment_count": 500,
      "comments": [
        {
          "author": "User1",
          "author_id": "UC...",
          "text": "Super video!",
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

| Endpoint | Methode | Description |
|----------|---------|-------------|
| `/` | GET | Interface web |
| `/api/channel-info` | POST | Infos de la chaine |
| `/api/scrape-comments` | POST | Extraction des commentaires |
| `/api/files` | GET | Liste des fichiers JSON |
| `/api/download/<filename>` | GET | Telecharger un fichier |

## Technologies

- **Backend** : Flask, yt-dlp
- **Frontend** : HTML/CSS/JavaScript, Plotly.js
- **Topic Modeling** (prevu) : scikit-learn, BERTopic, Gensim
- **NLP** (prevu) : spaCy, NLTK
- **Reduction dimensionnelle** (prevu) : UMAP, t-SNE

## Roadmap

- [x] Extraction des commentaires YouTube
- [x] Interface web avec onglets
- [x] Visualisation 3D (squelette)
- [ ] Pipeline de pre-traitement NLP
- [ ] Implementation LDA/NMF
- [ ] Integration BERTopic
- [ ] Visualisation interactive complete
- [ ] Export des resultats

## License

MIT
