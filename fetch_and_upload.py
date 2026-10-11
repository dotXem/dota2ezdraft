"""Daily job: fetch data from Stratz API and upload to GCS bucket."""
import datetime
import yaml
from google.cloud import storage
from get_data_from_stratz import get_data_from_stratz, HEROES


def load_previous_snapshot(bucket):
    """Return the most recent snapshot in the bucket, or None."""
    blobs = [blob for blob in bucket.list_blobs(prefix="data/") if blob.name.endswith(".yaml")]
    if not blobs:
        return None
    latest = max(blobs, key=lambda blob: blob.name)
    print(f"Fallback snapshot: {latest.name}")
    return yaml.safe_load(latest.download_as_text())


def main():
    client = storage.Client()
    bucket = client.bucket("heroes-ezdraft")

    print("Fetching data from Stratz...")
    data = get_data_from_stratz(fallback=load_previous_snapshot(bucket))
    nb_heroes = len(data.keys())

    if nb_heroes != len(HEROES):
        raise RuntimeError(f"Only fetched {nb_heroes}/{len(HEROES)} heroes")

    date = str(datetime.datetime.now().date())
    file_path = f"data/{date}.yaml"
    yaml_str = yaml.dump(data)

    blob = bucket.blob(file_path)
    blob.upload_from_string(yaml_str, content_type="text/yaml")

    print(f"Uploaded {file_path} to gs://heroes-ezdraft ({nb_heroes} heroes)")

if __name__ == "__main__":
    main()
