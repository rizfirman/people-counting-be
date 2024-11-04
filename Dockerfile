# Gunakan image Python sebagai base image
FROM python:3.12

# Set working directory di dalam container
WORKDIR /app

# Salin requirements file ke dalam container
COPY requirements.txt .

# Install dependencies
RUN python3 -m pip install --no-cache-dir -r requirements.txt

# Install libgl1 untuk OpenCV
RUN apt-get update && apt-get install -y libgl1 && rm -rf /var/lib/apt/lists/*

# Salin semua kode aplikasi ke dalam container
COPY . .



# Expose port yang digunakan aplikasi
EXPOSE 9000

# Menjalankan aplikasi menggunakan perintah berikut saat container dijalankan
CMD ["python", "app.py"]
