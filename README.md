# BLE Measurement Tool

A Streamlit-based web application designed for mapping and recording Bluetooth Low Energy (BLE) signals across indoor floor plans. 

For a complete breakdown of all capabilities, please see [FEATURES.md](FEATURES.md).

## Prerequisites

- **Python 3.10** or higher
- A machine with a functioning Bluetooth adapter
- *(Linux Only)*: To perform active BLE scanning without running as root, you must grant Bluetooth capabilities to your Python binary. 

## Setup Instructions

1. **Open a terminal** and navigate to the project directory.

2. **Create a virtual environment** to keep dependencies isolated:
   ```bash
   python -m venv venv
   ```

3. **Activate the virtual environment**:
   - **Linux/macOS**:
     ```bash
     source venv/bin/activate
     ```
   - **Windows** (Command Prompt):
     ```cmd
     venv\Scripts\activate
     ```
   - **Windows** (PowerShell):
     ```powershell
     .\venv\Scripts\Activate.ps1
     ```

4. **Install the required dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

### 🐧 Linux-Specific Bluetooth Permissions
If you are running on Linux, the `bleak` scanner requires special permissions to perform active scans. You can grant these to your virtual environment's Python executable by running:
```bash
sudo setcap 'cap_net_raw,cap_net_admin+eip' venv/bin/python
```

## Running the Application

Make sure your virtual environment is activated, then start the Streamlit server:

```bash
streamlit run app.py
```

Streamlit will automatically open a browser window pointing to the app (usually `http://localhost:8501`).

## Quickstart Guide

1. **Start a Campaign**: Enter a name for your measurement campaign and upload a floor plan image (e.g., `floor-plan-uc.jpg`).
2. **Scale the Grid**: Use the *Pixels per meter* slider in the left sidebar to calibrate the superimposed grid to your floor plan's actual scale.
3. **Clean the Map**: If your floor plan has distracting background colors, use the *Strip colour* tool in the sidebar to make those areas transparent.
4. **Take a Measurement**: 
   - Click a cell on the grid to indicate your physical location (True Position). 
   - Click **Capture snapshot**. 
   - After the 3-second scan, click the map again to mark where your phone *thinks* you are (App Reported Position).
   - Answer the beacon prompt and click **Save**.
5. **Export**: Use the buttons below the data table to download your full campaign as a CSV or JSON file at any time. All data is also auto-saved in the `campaigns/` folder.

## Project Structure

- `app.py`: The main Streamlit web interface and session state machine.
- `scanner.py`: The asynchronous Bluetooth scanning engine (powered by `bleak`).
- `image_processing.py`: High-performance Pillow (PIL) routines for rendering grids, zoom scaling, and color stripping.
- `models.py`: Dataclasses defining a `Measurement`, `ScanResult`, and `GridCell`.
- `session_store.py`: Logic for saving and parsing CSV aggregates and JSON raw data backups.
- `campaign.py`: Management logic for campaign folders, settings, and floor plan persistence.
- `campaigns/`: The local storage directory where all measurement databases are saved.
