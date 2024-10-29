## Counting People API

### Dependencies
- Python 3.11
- Postgres 16

### How to run
- Create virtual environment
`python -m venv venv`
- Install Dependencies
`python -m pip install -r requirements.txt`
- Run HTTP Server
`uvicorn app:app --host 0.0.0.0 --port 9000`