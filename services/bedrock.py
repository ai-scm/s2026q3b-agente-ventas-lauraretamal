"""Cliente Amazon Bedrock reutilizado desde el taller original."""

from dotenv import load_dotenv
load_dotenv()

import os

REGION_NAME = "us-east-1"
MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "amazon.nova-pro-v1:0")
