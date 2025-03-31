# Restore Google Photos Metadata

This guide provides step-by-step instructions to restore Google Photos metadata using a Python script.

## Prerequisites
Ensure you have the following installed on your macOS system using Homebrew:

```bash
brew install exiftool
brew install ffmpeg
brew install python@3.13
```

## Setup
1. Navigate to the project directory:

```bash
cd /path/to/project
```

2. Create a virtual environment:

```bash
python3.13 -m venv venv
source venv/bin/activate
```

3. Install the required dependencies:

```bash
pip install -r requirements.txt
```

## Usage
Run the script using the following command:

```bash
python Restore\ Google\ Photos\ Metadata.py
```

It will prompt you to enter the path to your Google Takeout data. Provide the full path (e.g., `/Volumes/T9/Takeout`) and press **Enter**.

## Notes
- Ensure you have the correct permissions to access the directory.
- The script will automatically restore the metadata for your photos.

## Troubleshooting
- If you encounter any issues with `ffmpeg` or `exiftool`, ensure they are correctly installed using `brew doctor`.
- Confirm Python 3.13 is installed by running `python3.13 --version`.

## License
This project is licensed under the MIT License.

