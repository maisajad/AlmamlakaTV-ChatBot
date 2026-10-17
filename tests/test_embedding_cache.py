import numpy as np

from app import embedding_cache as ec


class CountingEmbedder:
    def __init__(self):
        self.seen = []

    def __call__(self, texts):
        self.seen.extend(texts)
        return np.ones((len(texts), 3), dtype=np.float32)


def write_cache(path, model_id, texts):
    np.savez(path, model=np.array(model_id), keys=np.array([ec.key(t) for t in texts]),
             vectors=np.full((len(texts), 3), 2.0, dtype=np.float32))


def test_cached_vectors_are_used_and_only_new_text_is_embedded(tmp_path):
    path = tmp_path / "cache.npz"
    write_cache(path, "model-a", ["passage: old"])
    embed = CountingEmbedder()
    vectors = ec.embed_passages(["passage: old", "passage: new"], embed, "model-a", path)
    assert embed.seen == ["passage: new"]
    assert vectors[0].tolist() == [2.0, 2.0, 2.0] and vectors[1].tolist() == [1.0, 1.0, 1.0]


def test_cache_from_another_model_is_ignored(tmp_path):
    path = tmp_path / "cache.npz"
    write_cache(path, "model-a", ["passage: old"])
    embed = CountingEmbedder()
    ec.embed_passages(["passage: old"], embed, "model-b", path)
    assert embed.seen == ["passage: old"]  # different vector space: recomputed


def test_no_model_id_means_no_cache(tmp_path):
    path = tmp_path / "cache.npz"
    write_cache(path, "model-a", ["passage: old"])
    embed = CountingEmbedder()
    ec.embed_passages(["passage: old"], embed, None, path)
    assert embed.seen == ["passage: old"]
