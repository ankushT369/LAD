# Log Anomaly Detection (LAD) Project

## Overview
This project implements a log anomaly detection system using Docker, Fluentd, and a Python-based daemon along with a vector database (Qdrant) for similarity search. The system collects logs from multiple systems, processes them, and identifies anomalies using vector similarity search.

## Prerequisites
- Docker
- Python 3.11+
- Qdrant vector database (pre-workloaded with data)

## Project Structure
```
.
├── Apache_2k.log
├── config
├── consumer
├── daemon
│   ├── config.yaml
│   ├── daemon.py
│   ├── docker_run
│   ├── fluent.conf
│   └── logs
│       ├── data.log
│       │   ├── buffer.b63e73b26bbfd658b031d77c9c8cebd82.log
│       │   └── buffer.b63e73b26bbfd658b031d77c9c8cebd82.log.meta
│       ├── data.log.20250907.log
│       ├── data.log.20250908.log
│       ├── data.log.20250910.log
│       ├── data.log.20250911.log
│       └── data.log.20250912.log
├── docs
├── e88ebbacb848b09e477d11eedf4209d10ea4ac0a-1399x537.webp
├── frontend
├── README.md
├── scripts
│   ├── client.py
│   ├── log_ingestion.py
│   ├── main.py
│   ├── __pycache__
│   │   ├── client.cpython-311.pyc
│   │   ├── rag_chain.cpython-311.pyc
│   │   ├── text_utils.cpython-311.pyc
│   │   └── vectorstore.cpython-311.pyc
│   ├── rag_chain.py
│   ├── text_utils.py
│   └── vectorstore.py
├── tests
└── Windows_2k.log
```

## Setup and Running the Project

### Step 1: Run Fluentd Docker Container
- Start the Fluentd service using Docker. Use the `docker_run` script located in the `daemon` directory:
  ```bash
  cd daemon
  ./docker_run
  ```
- This will set up the Fluentd instance to handle log ingestion.

### Step 2: Configure and Run the Daemon
- The daemon retrieves logs from the paths specified in `config.yaml` (located in `daemon/`).
- Run the daemon script with the configuration file:
  ```bash
  python daemon.py config.yaml
  ```
- The daemon will collect logs and store them into the Fluentd buffer (e.g., `buffer.b63e73b26bbfd658b031d77c9c8cebd82.log`).

### Step 3: Fetch Logs from Fluentd
- The system fetches logs from the Fluentd buffer files generated in the `daemon/logs` directory.

### Step 4: Run the Main Script for Anomaly Detection
- Execute the `main.py` script to process the logs and perform anomaly detection:
  ```bash
  python scripts/main.py
  ```
- This script reads the logs from the buffer files, queries the pre-workloaded Qdrant vector database, and performs a vector similarity search to identify anomalies.

## How It Works
1. **Log Collection**: The daemon collects logs from multiple systems (System 1, System 2, System 3) and sends them to Fluentd via Kafka or Fluentd.
2. **Data Processing**: Logs are buffered and stored in the `daemon/logs` directory.
3. **Anomaly Detection**: The `main.py` script consumes the buffered data, queries the Qdrant cluster, and uses vector similarity search to detect anomalies.
4. **Results**: The results are displayed via the UI.

## Configuration
- Edit `daemon/config.yaml` to specify the log file paths and other settings as needed.

## Notes
- Ensure the Qdrant vector database is pre-workloaded with data for the similarity search to work effectively.
- Check the `logs` directory for buffered log files and historical data logs.

