from core.interface import DataSourceInterface
import ftplib
import csv
import io
from typing import Dict, Any

class BomFtpClient(DataSourceInterface):
    def __init__(self, host: str, remote_dir: str, file_name: str):
        self.host = host
        self.remote_dir = remote_dir
        self.file_name = file_name
        self.ftp = ftplib.FTP()

    def connect(self) -> bool:
        try:
            self.ftp.connect(self.host, 21, timeout=10)
            self.ftp.login()
            self.ftp.cwd(self.remote_dir)
            return True
        except Exception:
            return False

    def fetch_data(self) -> Dict[str, Any]:
        mem_file = io.BytesIO()
        try:
            self.ftp.retrbinary(f"RETR {self.file_name}", mem_file.write)
            mem_file.seek(0)
            csv_text = mem_file.read().decode('utf-8')
            reader = csv.reader(io.StringIO(csv_text))
            rows = list(reader)
            if len(rows) > 1:
                latest_record = rows[-1]
                return {"bom_air_temp": float(latest_record[1]) if len(latest_record) > 1 else 0.0}
        except Exception as e:
            print(f"BOM extraction failed: {e}")
        return {"bom_air_temp": 0.0}

    def disconnect(self) -> None:
        try:
            self.ftp.quit()
        except:
            pass
