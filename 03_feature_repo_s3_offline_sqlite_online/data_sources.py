from feast import FileSource
import s3fs

bucket_name = "featurestore"
file_name = "driver_stats.parquet"
s3_endpoint = "http://minio.kubeflow:9000"

s3 = s3fs.S3FileSystem(key='minio',
                       secret='RL4YSFL8TT39BBHZO7SKNYOG6Y5TDD',
                       client_kwargs={'endpoint_url': s3_endpoint}, use_ssl=False)

driver_stats = FileSource(
    name="driver_stats_source",
    path="s3://featurestore/infra/driver_stats.parquet",  # TODO: Replace with your bucket
    s3_endpoint_override="http://minio.kubeflow:9000",  # Needed since s3fs defaults to us-east-1
    timestamp_field="event_timestamp",
    created_timestamp_column="created",
    description="A table describing the stats of a driver based on hourly logs",
    owner="test2@gmail.com",
)
