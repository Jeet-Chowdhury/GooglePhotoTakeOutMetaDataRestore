import json
import os
import subprocess
from datetime import datetime
import glob
import signal
import threading
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

shutdown_event = threading.Event()
success_count = 0
failure_count = 0
failure_details = []


def signal_handler(sig, frame):
    tqdm.write("\nCtrl + C detected. Shutting down gracefully...")
    shutdown_event.set()


def format_timestamp(timestamp):
    try:
        return datetime.fromtimestamp(int(timestamp)).strftime("%Y:%m:%d %H:%M:%S")
    except (ValueError, TypeError):
        return None


def repair_corrupted_image(image_path):
    try:
        temp_path = image_path + "_repaired.jpg"
        command = [
            "ffmpeg",
            "-i",
            image_path,
            "-vf",
            "scale=iw:ih",
            "-c:v",
            "libjpeg",
            temp_path,
        ]
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode == 0:
            os.replace(temp_path, image_path)
            tqdm.write(f"Successfully repaired: {image_path}")
            return True
        else:
            tqdm.write(
                f"Repair failed for {image_path}: {result.stderr.decode().strip()}"
            )
            return False
    except Exception as e:
        tqdm.write(f"Error repairing {image_path}: {e}")
        return False


def delete_temp_files(directory):
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith("_exiftool_tmp"):
                temp_path = os.path.join(root, file)
                try:
                    os.remove(temp_path)
                    tqdm.write(f"Deleted temp file: {temp_path}")
                except Exception as e:
                    tqdm.write(f"Failed to delete temp file {temp_path}: {e}")


def convert_to_mp4(avi_path):
    try:
        mp4_path = os.path.splitext(avi_path)[0] + ".mp4"
        command = [
            "ffmpeg",
            "-y",
            "-i",
            avi_path,
            "-c:v",
            "libx264",
            "-preset",
            "slow",
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            mp4_path,
        ]
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode == 0:
            os.remove(avi_path)
            tqdm.write(f"Converted and deleted: {avi_path}")
            return mp4_path
        else:
            tqdm.write(
                f"Conversion failed for {avi_path}: {result.stderr.decode().strip()}"
            )
            return None
    except Exception as e:
        tqdm.write(f"Error converting {avi_path}: {e}")
        return None


def apply_metadata(image_path, json_path, progress_bar):
    global success_count, failure_count, failure_details

    if shutdown_event.is_set():
        return

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        creation_time = photo_taken_time = format_timestamp(
            data.get("photoTakenTime", {}).get("timestamp")
        )
        geo_data = data.get("geoData", {})
        people = [person.get("name", "")[:64] for person in data.get("people", [])]

        # Set negative altitude to 0
        altitude = max(geo_data.get("altitude", 0.0), 0.0)

        command = ["exiftool", "-overwrite_original", "-m"]

        if photo_taken_time:
            command.extend(
                [
                    f"-DateTimeOriginal={photo_taken_time}",
                    f"-CreateDate={photo_taken_time}",
                ]
            )

        if creation_time:
            command.extend(
                [f"-FileCreateDate={creation_time}", f"-FileModifyDate={creation_time}"]
            )

        command.extend(
            [
                f"-GPSLatitude={geo_data.get('latitude', 0)}",
                f"-GPSLongitude={geo_data.get('longitude', 0)}",
                f"-GPSAltitude={altitude}",
            ]
        )

        for name in people:
            command.append(f"-Keywords={name}")

        command.append(image_path)

        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode == 0:
            success_count += 1
        else:
            error_message = result.stderr.decode().strip() or "Unknown Error"

            if "Error reading OtherImageStart" in error_message:
                tqdm.write(f"Attempting to repair corrupted metadata for {image_path}")
                repair_command = [
                    "exiftool",
                    "-all=",
                    "-overwrite_original",
                    image_path,
                ]
                subprocess.run(repair_command)
                tqdm.write(f"Metadata repaired for {image_path}. Retrying...")
                subprocess.run(command)
            elif "JPEG EOI marker not found" in error_message:
                tqdm.write(
                    f"Detected corrupted JPEG. Attempting repair using ffmpeg: {image_path}"
                )
                if repair_corrupted_image(image_path):
                    tqdm.write(
                        f"Retrying metadata application for repaired image: {image_path}"
                    )
                    subprocess.run(command)
            else:
                failure_count += 1
                failure_details.append((image_path, error_message))
                tqdm.write(f"Error processing {image_path}: {error_message}")

    except Exception as e:
        failure_count += 1
        failure_details.append((image_path, str(e)))
        tqdm.write(f"Error processing {image_path}: {e}")


def find_json_file(image_path):
    # Remove Edit Suffix
    image_path = image_path.replace("-EFFECTS-edited", "")
    image_path = image_path.replace("-edited", "")
    image_path = image_path.replace("-edi", "")

    base_name = os.path.basename(image_path)
    dir_name = os.path.dirname(image_path)
    base_name_no_ext, ext = os.path.splitext(base_name)

    match = re.search(r"\((\d+)\)$", base_name_no_ext)
    number_suffix = match.group(1) if match else None
    clean_base_name = re.sub(r"\(\d+\)$", "", base_name_no_ext).strip()

    patterns = [
        f"{base_name}.json",
        f"{base_name[:-1]}.json",
        f"{base_name_no_ext}*.json",
        f"{base_name_no_ext[:-1]}*.json",
        f"{clean_base_name}.supplemental-metadata*.json",
        f"{clean_base_name}{ext}.supplemental-metadata*.json",
        f"{clean_base_name}.supplemental-metadat*.json",
        f"{clean_base_name}{ext}.supplemental-metadat*.json",
        f"{clean_base_name}.supplemental-*.json",
        f"{clean_base_name}{ext}.supplemental-*.json",
    ]

    if number_suffix:
        patterns.append(
            f"{clean_base_name}{ext}.supplemental-metadata({number_suffix}).json"
        )
        patterns.append(
            f"{clean_base_name}{ext}.supplemental-metadat({number_suffix}).json"
        )
        patterns.append(f"{clean_base_name}{ext}.supplemental-({number_suffix}).json")
        patterns.append(
            f"{clean_base_name[:-1]}{ext}.supplemental-metadata({number_suffix}).json"
        )
        patterns.append(
            f"{clean_base_name[:-1]}{ext}.supplemental-metadat({number_suffix}).json"
        )
        patterns.append(
            f"{clean_base_name[:-1]}{ext}.supplemental-({number_suffix}).json"
        )
        patterns.append(f"{clean_base_name[:-1]}*.json")

    for pattern in patterns:
        json_files = glob.glob(os.path.join(dir_name, pattern))
        # tqdm.write(f"Checked: {os.path.join(dir_name, pattern)} - {'Match Found' if json_files else 'No Match'}")
        if json_files:
            return json_files[0]

    return None


def is_jpeg(file_path):
    try:
        result = subprocess.run(
            ["file", file_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return "JPEG image data" in result.stdout
    except Exception as e:
        tqdm.write(f"Error checking file type: {e}")
        return False


def check_and_rename(file_path):
    if file_path.lower().endswith(".heic") and is_jpeg(file_path):
        new_path = os.path.splitext(file_path)[0] + ".jpg"
        try:
            os.rename(file_path, new_path)
            tqdm.write(f"Renamed to: {new_path}")
            return new_path
        except Exception as e:
            tqdm.write(f"Failed to rename {file_path}: {e}")
            return None
    return file_path


def process_file(image_path, progress_bar):
    if shutdown_event.is_set():
        return

    tqdm.write(f"Processing {image_path}")
    if image_path.lower().endswith(".avi"):
        image_path = convert_to_mp4(image_path)
        if not image_path:
            return

    json_path = find_json_file(image_path)
    if json_path:
        apply_metadata(image_path, json_path, progress_bar)
    else:
        tqdm.write(f"No JSON found for {image_path}")
        global failure_count
        failure_count += 1
        failure_details.append((image_path, "No JSON file found"))
    progress_bar.update(1)


def delete_json_files(directory):
    try:
        for root, _, files in os.walk(directory):
            for file in files:
                if file.endswith(".json"):
                    json_path = os.path.join(root, file)
                    os.remove(json_path)
                    tqdm.write(f"Deleted JSON: {json_path}")
    except Exception as e:
        tqdm.write(f"Error deleting JSON files: {e}")


def process_directory(directory):
    delete_temp_files(directory)
    image_files = []
    for root, _, files in os.walk(directory):
        for file in files:
            if file.startswith("._"):
                continue
            if file.lower().endswith(
                (
                    ".jpg",
                    ".jpeg",
                    ".png",
                    ".heic",
                    ".mp4",
                    ".mov",
                    ".avi",
                    ".mkv",
                    ".webm",
                    ".3gp",
                    ".m4v",
                    ".gif",
                    ".mp",
                )
            ):
                image_files.append(os.path.join(root, file))

    tqdm.write(f"Found {len(image_files)} image files. Starting parallel processing...")

    max_workers = min(32, os.cpu_count() or 1)
    tqdm.write(f"Using {max_workers} threads for processing.")

    with tqdm(
        total=len(image_files),
        desc="Processing files",
        unit="file",
        dynamic_ncols=True,
        position=0,
        leave=True,
    ) as progress_bar:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = []
            for image_path in image_files:
                image_path = check_and_rename(image_path)
                if image_path:
                    futures.append(
                        executor.submit(process_file, image_path, progress_bar)
                    )

            for future in as_completed(futures):
                if shutdown_event.is_set():
                    tqdm.write("Shutdown signal received. Stopping remaining tasks...")
                    executor.shutdown(wait=False)
                    break
                future.result()

        tqdm.write("All files processed.")
        tqdm.write(f"\nSummary: \nSuccess: {success_count}\nFailure: {failure_count}")
        if failure_count > 0:
            tqdm.write("\nFailure Details:")
            for path, reason in failure_details:
                tqdm.write(f"{path}: {reason}")

        if failure_count == 0:
            tqdm.write("✅ All images processed successfully. Deleting JSON files...")
            delete_json_files(directory)
        elif failure_count > 0:
            tqdm.write("\n❗ Some files failed. JSON files will not be deleted.")


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    directory = input("Enter the path to the folder for recursive processing: ").strip()
    if os.path.isdir(directory):
        process_directory(directory)
    else:
        tqdm.write("Invalid directory. Please enter a valid path.")
