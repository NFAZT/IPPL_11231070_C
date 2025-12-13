import json
from pathlib import Path

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

BASE_DIR = Path(__file__).resolve().parent
DATA_PATH = BASE_DIR / "data" / "question_train_data.json"
OUT_PATH = BASE_DIR / "data" / "intent_model.joblib"


def main():
    #baca data latihan
    with DATA_PATH.open(encoding="utf-8") as f:
        data = json.load(f)

    texts = [item["text"] for item in data]
    labels = [item["label"] for item in data]

    model = Pipeline([
        ("tfidf", TfidfVectorizer(ngram_range=(1, 2), min_df=1)),
        ("clf", LogisticRegression(max_iter=1000)),
    ])

    #latih model
    print(f"Melatih model intent pada {len(texts)} contoh...")
    model.fit(texts, labels)

    #simpan model
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, OUT_PATH)
    print(f"Model intent disimpan ke: {OUT_PATH}")


if __name__ == "__main__":
    main()