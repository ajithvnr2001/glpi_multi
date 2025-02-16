import os
from langchain_community.embeddings import HuggingFaceEmbeddings
from typing import List

class AkashEmbeddings(HuggingFaceEmbeddings):
    """HuggingFaceEmbeddings using the BAAI/bge-large-en-v1.5 model."""
    def __init__(self):
      super().__init__(model_name="BAAI/bge-large-en-v1.5")
