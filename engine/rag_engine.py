"""
RAG Engine with FAISS Vector Store
Skincare AI - Knowledge Retrieval System

Dependencies (install when network available):
    pip install faiss-cpu sentence-transformers numpy

In offline/mock mode: uses keyword-based TF-IDF-like retrieval
In production mode: uses sentence-transformers + FAISS
"""

import os
import re
import json
import math
import hashlib
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Any
from collections import defaultdict


# ─────────────────────────────────────────────
# DATA STRUCTURES
# ─────────────────────────────────────────────

class Chunk:
    """A logical unit of knowledge from the knowledge base."""
    def __init__(self, chunk_id: str, source_file: str, section: str,
                 content: str, structured_fields: Dict[str, Any]):
        self.chunk_id = chunk_id
        self.source_file = source_file
        self.section = section
        self.content = content
        self.structured_fields = structured_fields  # parsed YAML-like fields
        self.embedding: Optional[List[float]] = None

    def to_dict(self) -> Dict:
        return {
            "chunk_id": self.chunk_id,
            "source_file": self.source_file,
            "section": self.section,
            "content": self.content,
            "structured_fields": self.structured_fields
        }


class RetrievalResult:
    """A retrieved chunk with a relevance score."""
    def __init__(self, chunk: Chunk, score: float):
        self.chunk = chunk
        self.score = score


# ─────────────────────────────────────────────
# MARKDOWN PARSER
# ─────────────────────────────────────────────

class KnowledgeBaseParser:
    """
    Parses markdown knowledge base files into structured Chunk objects.
    Splits on '---' delimiters and extracts structured fields.
    """

    FIELD_PATTERN = re.compile(
        r'^([A-Z][A-Z_a-z0-9]*):\s*(.+)$', re.MULTILINE
    )
    LIST_PATTERN = re.compile(r'\[([^\]]*)\]')

    def parse_file(self, filepath: Path) -> List[Chunk]:
        """Parse a single markdown/text file into chunks."""
        text = filepath.read_text(encoding='utf-8')
        # Split by section separators '---'
        raw_sections = re.split(r'---', text)
        chunks = []
        for raw in raw_sections:
            raw = raw.strip()
            if not raw:
                continue
            # Skip top-level comment headers (single #) but keep ## sections
            if raw.startswith('#') and not raw.startswith('##'):
                continue
            chunk = self._parse_section(filepath.name, raw)
            if chunk:
                chunks.append(chunk)
        return chunks

    def _parse_section(self, source: str, text: str) -> Optional[Chunk]:
        """Parse a single section into a Chunk."""
        # Extract section title (## SKIN_TYPE: Normal)
        title_match = re.match(r'^##\s+(.+)', text, re.MULTILINE)
        section = title_match.group(1).strip() if title_match else "Unknown"

        # Extract structured key: value fields
        structured = {}
        for match in self.FIELD_PATTERN.finditer(text):
            key = match.group(1).strip()
            raw_val = match.group(2).strip()
            # Parse list values like [a, b, c]
            list_match = self.LIST_PATTERN.match(raw_val)
            if list_match:
                items = [i.strip() for i in list_match.group(1).split(',') if i.strip()]
                structured[key] = items
            elif raw_val.upper() in ('TRUE', 'FALSE'):
                structured[key] = raw_val.upper() == 'TRUE'
            elif raw_val.upper() == 'CAUTION':
                structured[key] = 'CAUTION'
            else:
                structured[key] = raw_val

        if not structured:
            return None

        chunk_id = hashlib.md5(f"{source}::{section}".encode()).hexdigest()[:12]
        return Chunk(
            chunk_id=chunk_id,
            source_file=source,
            section=section,
            content=text,
            structured_fields=structured
        )

    def parse_directory(self, directory: Path) -> List[Chunk]:
        """Parse all .md and .txt files in a directory recursively."""
        chunks = []
        for fpath in directory.rglob('*.md'):
            chunks.extend(self.parse_file(fpath))
        for fpath in directory.rglob('*.txt'):
            chunks.extend(self.parse_file(fpath))
        return chunks


# ─────────────────────────────────────────────
# MOCK EMBEDDING ENGINE (TF-IDF based)
# Replace with sentence-transformers in production
# ─────────────────────────────────────────────

class MockEmbeddingEngine:
    """
    TF-IDF inspired keyword embedding for offline use.
    In production, replace with:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer('all-MiniLM-L6-v2')
        embedding = model.encode(text)
    """

    def __init__(self):
        self.vocabulary: Dict[str, int] = {}
        self.idf: Dict[str, float] = {}
        self._fitted = False

    def _tokenize(self, text: str) -> List[str]:
        text = text.lower()
        # Keep compound words joined by underscore
        tokens = re.findall(r'[a-z][a-z_]*[a-z]', text)
        return tokens

    def fit(self, corpus: List[str]) -> None:
        """Build vocabulary and IDF from corpus."""
        # Count document frequency
        df: Dict[str, int] = defaultdict(int)
        tokenized = []
        for doc in corpus:
            tokens = set(self._tokenize(doc))
            tokenized.append(tokens)
            for t in tokens:
                df[t] += 1

        N = len(corpus)
        all_words = sorted(df.keys())
        self.vocabulary = {w: i for i, w in enumerate(all_words)}
        self.idf = {w: math.log((N + 1) / (df[w] + 1)) + 1 for w in all_words}
        self._fitted = True

    def encode(self, text: str) -> List[float]:
        """Encode text as TF-IDF vector."""
        if not self._fitted:
            raise RuntimeError("Call fit() before encode()")
        tokens = self._tokenize(text)
        tf: Dict[str, float] = defaultdict(float)
        for t in tokens:
            tf[t] += 1
        total = sum(tf.values()) or 1

        vec = [0.0] * len(self.vocabulary)
        for word, freq in tf.items():
            if word in self.vocabulary:
                idx = self.vocabulary[word]
                vec[idx] = (freq / total) * self.idf.get(word, 1.0)
        # L2 normalize
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def cosine_similarity(self, v1: List[float], v2: List[float]) -> float:
        dot = sum(a * b for a, b in zip(v1, v2))
        return dot  # already normalized


# ─────────────────────────────────────────────
# FAISS INDEX (Mock — real FAISS when installed)
# ─────────────────────────────────────────────

class MockFAISSIndex:
    """
    In-memory brute-force index.
    Replace with:
        import faiss
        index = faiss.IndexFlatIP(dim)
        index.add(np.array(embeddings))
        D, I = index.search(query_vec, top_k)
    """

    def __init__(self):
        self.vectors: List[List[float]] = []
        self.chunk_ids: List[str] = []

    def add(self, chunk_id: str, vector: List[float]) -> None:
        self.vectors.append(vector)
        self.chunk_ids.append(chunk_id)

    def search(self, query_vec: List[float], top_k: int) -> List[Tuple[str, float]]:
        if not self.vectors:
            return []
        scores = []
        for i, vec in enumerate(self.vectors):
            score = sum(a * b for a, b in zip(query_vec, vec))
            scores.append((self.chunk_ids[i], score))
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]


# ─────────────────────────────────────────────
# MAIN RAG ENGINE
# ─────────────────────────────────────────────

class RAGEngine:
    """
    Main retrieval engine.
    Parses knowledge base → embeds → indexes → retrieves on query.
    """

    def __init__(self, knowledge_base_dir: str):
        self.kb_dir = Path(knowledge_base_dir)
        self.parser = KnowledgeBaseParser()
        self.embedder = MockEmbeddingEngine()
        self.index = MockFAISSIndex()
        self.chunks: Dict[str, Chunk] = {}  # chunk_id -> Chunk
        self._built = False

    def build(self) -> None:
        """Parse, embed, and index all knowledge base files."""
        print(f"[RAGEngine] Parsing knowledge base from: {self.kb_dir}")
        all_chunks = self.parser.parse_directory(self.kb_dir)
        print(f"[RAGEngine] Parsed {len(all_chunks)} chunks")

        if not all_chunks:
            raise ValueError("No chunks found. Check knowledge base directory.")

        # Fit embedder on all content
        corpus = [c.content for c in all_chunks]
        self.embedder.fit(corpus)

        # Embed and index
        for chunk in all_chunks:
            vec = self.embedder.encode(chunk.content)
            chunk.embedding = vec
            self.index.add(chunk.chunk_id, vec)
            self.chunks[chunk.chunk_id] = chunk

        self._built = True
        print(f"[RAGEngine] Index built with {len(self.chunks)} chunks")

    def retrieve(self, query: str, top_k: int = 10,
                 source_filter: Optional[List[str]] = None) -> List[RetrievalResult]:
        """
        Retrieve top_k relevant chunks for a query.
        Optionally filter by source file names.
        """
        if not self._built:
            self.build()

        query_vec = self.embedder.encode(query)
        raw_results = self.index.search(query_vec, top_k * 3)  # over-fetch then filter

        results = []
        for chunk_id, score in raw_results:
            chunk = self.chunks.get(chunk_id)
            if not chunk:
                continue
            if source_filter and not any(s in chunk.source_file for s in source_filter):
                continue
            results.append(RetrievalResult(chunk, score))
            if len(results) >= top_k:
                break

        return results

    def retrieve_by_type(self, query: str, knowledge_types: List[str],
                         top_k: int = 5) -> Dict[str, List[RetrievalResult]]:
        """
        Retrieve from specific knowledge types simultaneously.
        Returns dict keyed by type (skin_types, ingredients, etc.)
        """
        type_to_file = {
            'skin_types': 'skin_types',
            'concerns': 'skin_concerns',
            'ingredients': 'ingredients',
            'allergies': 'allergies',
            'medical': 'allergies_medical',
            'products': 'products'
        }
        results = {}
        for ktype in knowledge_types:
            source_key = type_to_file.get(ktype, ktype)
            results[ktype] = self.retrieve(query, top_k=top_k,
                                           source_filter=[source_key])
        return results

    def get_chunk_by_section(self, section_keyword: str) -> Optional[Chunk]:
        """Direct lookup by section name keyword."""
        for chunk in self.chunks.values():
            if section_keyword.lower() in chunk.section.lower():
                return chunk
        return None

    def get_all_of_type(self, source_file_keyword: str) -> List[Chunk]:
        """Return all chunks from a particular source file."""
        return [c for c in self.chunks.values()
                if source_file_keyword.lower() in c.source_file.lower()]