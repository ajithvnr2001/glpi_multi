    import os
    from langchain_community.vectorstores import Chroma
    from langchain.chains import RetrievalQA
    from unstructured.partition.html import partition_html
    from typing import List, Dict, Optional
    from langchain_openai import OpenAI
    from langchain_huggingface import HuggingFaceEmbeddings
    import requests
    import json
    import base64
    import logging

    logger = logging.getLogger(__name__)

    class LLMService:
        """Handles interactions with LLMs for text and image processing."""

        def __init__(self, text_model_name: str = "Meta-Llama-3-1-8B-Instruct-FP8"):
            """Initializes the LLMService.

            Args:
                text_model_name: The name of the LLM model to use for text (from AkashChat).
            """
            self.text_model_name = text_model_name
            self.akash_api_key = os.environ.get("AKASH_API_KEY")
            self.akash_api_base = os.environ.get("AKASH_API_BASE", "https://chatapi.akash.network/api/v1")
            self.openrouter_api_key = os.environ.get("OPENROUTER_API_KEY")  # Get OpenRouter key
            self.openrouter_api_base = os.environ.get("OPENROUTER_API_BASE", "https://openrouter.ai/api/v1") # Get OpenRouter url

            if not self.akash_api_key:
                raise ValueError("AKASH_API_KEY environment variable not set.")
            if not self.openrouter_api_key:
                raise ValueError("OPENROUTER_API_KEY environment variable not set.")


            self.llm = OpenAI(
                model=self.text_model_name,
                api_key=self.akash_api_key,
                base_url=self.akash_api_base,
                temperature=0.2,
                max_tokens=1000,
            )
            logger.info(f"LLMService initialized with text model: {self.text_model_name}")


        def get_embedding_function(self):
            """Returns the HuggingFace embedding function."""
            return HuggingFaceEmbeddings(model_name="BAAI/bge-large-en-v1.5")

        def create_vectorstore(self, chunks: List[Dict]):
            """Creates a Chroma vector store from a list of text chunks."""
            texts = [chunk["text"] for chunk in chunks]
            metadatas = [
                {key: value for key, value in chunk.items() if key != "text"}
                for chunk in chunks
            ]
            embeddings = self.get_embedding_function()
            db = Chroma.from_texts(texts=texts, embedding=embeddings, metadatas=metadatas)
            logger.info(f"Created Chroma vector store with {len(chunks)} chunks.")
            return db

        def query_llm(self, db, query: str):
            """Queries the LLM using RetrievalQA (for text)."""
            qa = RetrievalQA.from_chain_type(
                llm=self.llm, chain_type="stuff", retriever=db.as_retriever(search_kwargs={'k': 1})
            )
            result = qa.invoke({"query": query})["result"]
            logger.info(f"LLM query result: {result}")
            return result

        def rag_completion(self, documents: List[Dict], query: str):
            """Performs RAG completion on text documents (using Akash)."""
            chunks = self.process_documents_to_chunks(documents)
            vector_store = self.create_vectorstore(chunks)
            return self.query_llm(vector_store, query)

        def process_documents_to_chunks(self, documents: List[Dict]) -> List[Dict]:
            """Processes GLPI documents and extracts text chunks."""
            chunks = []
            list_tags = ["ul", "ol", "li"]  # List of tags to include as list items
            for doc in documents:
                if "content" in doc:
                    content = doc["content"]
                    elements = partition_html(text=content, include_page_breaks=False, include_metadata=False, include_element_types=list_tags)
                    for element in elements:
                        chunks.append(
                            {
                                "text": str(element),
                                "source_id": doc.get("id"),
                                "source_type": "glpi_ticket",
                            }
                        )
            logger.info(f"Processed {len(documents)} documents into {len(chunks)} chunks.")
            return chunks


        def complete(self, prompt, context=None):
            """Completes a prompt using the OpenAI-compatible API (Akash)."""
            if context:
                prompt = context + prompt
            return self.llm.invoke(prompt)

        def process_image(self, image_data: str, prompt: str) -> Optional[str]:
            """Processes an image using the OpenRouter API (Qwen).  NO FILE PATH.

            Args:
                image_data: Base64 encoded image data.
                prompt: The prompt for the image model.

            Returns:
                The LLM's response, or None if an error occurred.
            """
            try:
                headers = {
                    "Authorization": f"Bearer {self.openrouter_api_key}",
                    # Removed  "HTTP-Referer" and "X-Title"
                }
                payload = {
                    "model": "qwen/qwen2.5-vl-72b-instruct:free",  # Use the correct model name
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/jpeg;base64,{image_data}"
                                    },
                                 }
                            ]
                        }
                    ],

                }
                response = requests.post(
                    f"{self.openrouter_api_base}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)
                result = response.json()["choices"][0]["message"]["content"]
                logger.info(f"Image processing result: {result}")
                return result

            except requests.exceptions.RequestException as e:
                logger.error(f"Error processing image with OpenRouter: {e}", exc_info=True)
                return None
            except (KeyError, IndexError) as e:
                logger.error(f"Unexpected response format from OpenRouter: {e}", exc_info=True)
                return None
            except Exception as e:
                logger.error(f"Error during image processing {e}", exc_info=True)
                return None
