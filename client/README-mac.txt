BRAIN Client dla macOS

Binarka macOS wymaga zbudowania na komputerze Mac (PyInstaller nie cross-kompiluje).

Wkrótce: BrainClient dla macOS pojawi się tutaj jako jeden plik do pobrania.

Tymczasowo użyj Windows lub Linux, albo zbuduj ze źródeł na Mac:
  cd /opt/BRAIN/client && pip install -e . pyinstaller pillow pystray
  pyinstaller --onefile --windowed --name BrainClient brain_client/__main__.py
