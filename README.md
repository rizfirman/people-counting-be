# Counting People API

## Overview
This API provides functionality for counting people in various contexts.

## Prerequisites
Make sure you have the following installed on your machine:

- **Python**: Version 3.11
- **PostgreSQL**: Version 16

## Getting Started

Follow these steps to set up and run the API:

1. **Create a Virtual Environment**
   ```bash
   python -m venv venv
   ```

2. **Activate the Virtual Environment**
   - **On Windows:**
     ```bash
     venv\Scripts\activate
     ```
   - **On macOS/Linux:**
     ```bash
     source venv/bin/activate
     ```

3. **Install Dependencies**
   ```bash
   python -m pip install -r requirements.txt
   ```

4. **Run the HTTP Server**
   ```bash
   uvicorn app:app --host 0.0.0.0 --port 9000
   ```

Now your API should be up and running on `http://localhost:9000`.