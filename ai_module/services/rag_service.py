import os
import re
import json
import zlib
import zipfile
import math
from datetime import datetime

class RAGService:
    def __init__(self, kb_dir=None):
        if kb_dir is None:
            # Place knowledge base in the module's folder
            self.kb_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "knowledge_base")
        else:
            self.kb_dir = kb_dir
            
        os.makedirs(self.kb_dir, exist_ok=True)
        self.metadata_file = os.path.join(self.kb_dir, "metadata.json")
        self.index_file = os.path.join(self.kb_dir, "index.json")
        self._load_metadata()
        self._load_index()

    def _load_metadata(self):
        if os.path.exists(self.metadata_file):
            try:
                with open(self.metadata_file, 'r', encoding='utf-8') as f:
                    self.metadata = json.load(f)
            except:
                self.metadata = {}
        else:
            self.metadata = {}

    def _save_metadata(self):
        with open(self.metadata_file, 'w', encoding='utf-8') as f:
            json.dump(self.metadata, f, indent=2, ensure_ascii=False)

    def _load_index(self):
        if os.path.exists(self.index_file):
            try:
                with open(self.index_file, 'r', encoding='utf-8') as f:
                    self.index_data = json.load(f)
            except:
                self.index_data = {"chunks": [], "vocab": {}, "idf": {}}
        else:
            self.index_data = {"chunks": [], "vocab": {}, "idf": {}}

    def _save_index(self):
        with open(self.index_file, 'w', encoding='utf-8') as f:
            json.dump(self.index_data, f, indent=2, ensure_ascii=False)

    def extract_text_from_file(self, filepath, ext):
        ext = ext.lower().lstrip('.')
        if ext == 'txt':
            try:
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    return f.read()
            except Exception as e:
                return f"Error reading text file: {e}"
                
        elif ext == 'docx':
            return self._extract_docx(filepath)
            
        elif ext == 'pdf':
            return self._extract_pdf(filepath)
            
        return ""

    def _extract_docx(self, filepath):
        try:
            # Word files (.docx) are zipped XML structures. 
            # We can extract the body text from word/document.xml without external libs!
            text_runs = []
            with zipfile.ZipFile(filepath) as z:
                xml_content = z.read('word/document.xml').decode('utf-8', errors='ignore')
                # Find all <w:t> tags containing actual text strings
                for text_match in re.finditer(r'<w:t[^>]*>(.*?)</w:t>', xml_content):
                    text_runs.append(text_match.group(1))
            return "\n".join(text_runs)
        except Exception as e:
            return f"Error parsing DOCX file: {e}"

    def _extract_pdf(self, filepath):
        # 1. Try standard pypdf package first
        try:
            import pypdf
            reader = pypdf.PdfReader(filepath)
            text = ""
            for page in reader.pages:
                t = page.extract_text()
                if t:
                    text += t + "\n"
            if text.strip():
                return text
        except ImportError:
            pass
        except Exception as e:
            pass

        # 2. Fall back to lightweight robust pure-python stream-decoder
        try:
            text_content = []
            with open(filepath, 'rb') as f:
                content = f.read()
            
            # Find stream segments in the PDF file
            stream_matches = re.finditer(rb'stream\r?\n(.*?)\r?\nendstream', content, re.DOTALL)
            for match in stream_matches:
                stream_data = match.group(1)
                try:
                    # Decompress deflated stream data
                    decompressed = zlib.decompress(stream_data)
                except:
                    try:
                        # Decompress with raw deflate if header is missing
                        decompressed = zlib.decompress(stream_data, -15)
                    except:
                        continue
                
                # Extract text chunks enclosed in parentheses: (text) Tj
                strings = re.findall(rb'\((.*?)\)', decompressed)
                for s in strings:
                    try:
                        decoded = s.decode('utf-8', errors='ignore')
                        # Sanitize escaped PDF backslashes
                        decoded = decoded.replace(r'\(', '(').replace(r'\)', ')').replace(r'\\', '\\')
                        text_content.append(decoded)
                    except:
                        pass
                        
            extracted = " ".join(text_content)
            # Basic formatting cleanup
            extracted = re.sub(r'\s+', ' ', extracted)
            return extracted if extracted.strip() else "PDF contains no extractable text or uses custom fonts."
        except Exception as e:
            return f"Error extracting text from PDF: {e}"

    def add_document(self, filename, filepath, original_name):
        ext = os.path.splitext(filename)[1]
        text = self.extract_text_from_file(filepath, ext)
        
        # Save metadata
        self.metadata[filename] = {
            "original_name": original_name,
            "size": os.path.getsize(filepath),
            "uploaded_at": datetime.now().isoformat(),
            "char_count": len(text)
        }
        self._save_metadata()
        
        # Create text chunks
        chunks = self._chunk_text(text, filename, original_name)
        
        # Append to existing index chunks (filtering out old ones from this file if any)
        self.index_data["chunks"] = [c for c in self.index_data["chunks"] if c["file"] != filename]
        self.index_data["chunks"].extend(chunks)
        
        # Re-build Lexical Index
        self._build_lexical_index()
        self._save_index()
        return True

    def delete_document(self, filename):
        if filename in self.metadata:
            del self.metadata[filename]
            self._save_metadata()
            
            # Remove file on disk
            path = os.path.join(self.kb_dir, filename)
            if os.path.exists(path):
                try:
                    os.remove(path)
                except:
                    pass
            
            # Remove from index chunks
            self.index_data["chunks"] = [c for c in self.index_data["chunks"] if c["file"] != filename]
            
            # Re-build Lexical Index
            self._build_lexical_index()
            self._save_index()
            return True
        return False

    def _chunk_text(self, text, filename, original_name, chunk_size=600, overlap=120):
        chunks = []
        if not text.strip():
            return chunks
            
        # Clean white spaces
        text = re.sub(r'\s+', ' ', text)
        
        start = 0
        idx = 0
        while start < len(text):
            end = min(start + chunk_size, len(text))
            
            # Try to slide end back to a word or sentence boundary to preserve readability
            if end < len(text):
                # Look for sentence boundary or period
                boundary = -1
                for char_idx in range(end, max(end - 100, start), -1):
                    if text[char_idx] in ['.', '!', '?', '\n']:
                        boundary = char_idx + 1
                        break
                if boundary != -1:
                    end = boundary
                else:
                    # Look for space boundary
                    for char_idx in range(end, max(end - 40, start), -1):
                        if text[char_idx] == ' ':
                            end = char_idx
                            break
            
            chunk_text = text[start:end].strip()
            if len(chunk_text) > 40: # Ignore tiny useless chunks
                chunks.append({
                    "id": f"{filename}_{idx}",
                    "file": filename,
                    "original_name": original_name,
                    "text": chunk_text,
                    "index": idx
                })
                idx += 1
                
            start = end - overlap
            if start >= len(text) or (end == len(text)):
                break
        return chunks

    def _build_lexical_index(self):
        # A lightweight TF-IDF indexing implementation to allow dependency-free lexical search
        chunks = self.index_data.get("chunks", [])
        
        # Tokenize and compute document frequencies
        vocab = {}
        idf = {}
        doc_count = len(chunks)
        
        if doc_count == 0:
            self.index_data["vocab"] = vocab
            self.index_data["idf"] = idf
            return
            
        def tokenize(text):
            return re.findall(r'\b\w{3,20}\b', text.lower())

        # Track token frequencies per chunk
        for chunk in chunks:
            tokens = tokenize(chunk["text"])
            tf = {}
            for t in tokens:
                tf[t] = tf.get(t, 0) + 1
            chunk["tf"] = tf
            
            # Update vocab count
            for t in tf:
                vocab[t] = vocab.get(t, 0) + 1

        # Calculate IDF values
        for t, df in vocab.items():
            idf[t] = math.log((1 + doc_count) / (1 + df)) + 1
            
        self.index_data["vocab"] = vocab
        self.index_data["idf"] = idf

    def retrieve_context(self, query, top_k=4):
        chunks = self.index_data.get("chunks", [])
        if not chunks:
            return []
            
        # Clean query tokens
        query_tokens = re.findall(r'\b\w{3,20}\b', query.lower())
        if not query_tokens:
            # Fall back to returning top matches
            return chunks[:top_k]
            
        idf = self.index_data.get("idf", {})
        
        # Calculate cosine similarity or BM25-like scores
        scored_chunks = []
        for chunk in chunks:
            tf = chunk.get("tf", {})
            score = 0.0
            
            # Simple TF-IDF score summation
            for token in query_tokens:
                if token in tf and token in idf:
                    # Term frequency weight * inverse document frequency
                    score += (tf[token] * idf[token])
                    
            # Boost score slightly if chunk belongs to a highly relevant topic/keywords match
            if score > 0:
                scored_chunks.append((score, chunk))
                
        # Sort by score descending
        scored_chunks.sort(key=lambda x: x[0], reverse=True)
        
        # Return top K chunks (without the score and intermediate token counts)
        results = []
        for score, chunk in scored_chunks[:top_k]:
            results.append({
                "original_name": chunk.get("original_name"),
                "text": chunk.get("text"),
                "score": score
            })
            
        return results

    def reindex_all(self):
        # Clears and indexes all files inside kb_dir from scratch
        self.index_data = {"chunks": [], "vocab": {}, "idf": {}}
        self._load_metadata()
        
        for filename in list(self.metadata.keys()):
            filepath = os.path.join(self.kb_dir, filename)
            if os.path.exists(filepath):
                original_name = self.metadata[filename].get("original_name", filename)
                self.add_document(filename, filepath, original_name)
            else:
                del self.metadata[filename]
                
        self._save_metadata()
        return True

rag_service = RAGService()
