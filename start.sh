#!/bin/bash

echo "Running ingestion..."
python ingest.py

echo "Starting Streamlit..."
streamlit run ui.py --server.port 10000 --server.address 0.0.0.0