<h1>Module 0: Setting up a feature repo, sharing features, train model</h1>

Welcome! Here we use a basic example to explain key concepts and user flows in Feast. 

We focus on a specific example (that does not include online features or realtime models):
- **Goal**: build a platform for data scientists and engineers to share features for training offline models
  
<h2>Table of Contents</h2>

- [Installing Feast](#installing-feast)
- [Exploring the data](#exploring-the-data)
- [Reviewing Feast concepts](#reviewing-feast-concepts)
  - [A quick primer on feature views](#a-quick-primer-on-feature-views)
- [User groups](#user-groups)
  - [User group 1: ML Platform Team](#user-group-1-ml-platform-team)
    - [Step 0 (MinIO): Setup S3 bucket for registry and file sources](#step-0-aws-setup-s3-bucket-for-registry-and-file-sources)
    - [Step 1: Setup the feature repo](#step-1-setup-the-feature-repo)
      - [Step 1a: Use your configured bucket](#step-1a-use-your-configured-bucket)
      - [Some further notes and gotchas](#some-further-notes-and-gotchas)
      - [Step 1b: Run `feast plan`](#step-1b-run-feast-plan)
      - [Step 1c: Run `feast apply`](#step-1c-run-feast-apply)
      - [Step 1d: Verify features are registered](#step-1d-verify-features-are-registered)
    - [Step 2: Setup a Web UI endpoint](#step-2-setup-a-web-ui-endpoint)


# Installing Feast
Before we get started, first install Feast and others' dependencies:
- Local
  ```bash
    pip install feast==0.29.0
    pip install scikit-learn
    pip install boto3
    pip install s3fs
  ```

# Exploring the data
We've made some dummy data for this workshop in `infra/driver_stats.parquet`. Let's dive into what the data looks like. You can follow along in [explore-driver-data.ipynb](explore-data.ipynb):

```python
import pandas as pd
pd.read_parquet("infra/driver_stats.parquet")
```

![](dataset.png)

This is a set of time-series data with `driver_id` as the primary key (representing the driver entity) and `event_timestamp` as showing when the event happened. 

# Reviewing Feast concepts
Let's quickly review some Feast concepts needed to build this ML platform / use case. Don't worry about committing all this to heart. We explore these concepts by example throughout the workshop.
| Concept&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; | Description                                                                                                                                                                                                                                                                                                                                                                                               |
| :------------------------------------------------------------------------------ | :-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Data source                                                                     | We need a `FileSource` (with an S3 path and endpoint override) to represent the `driver_stats.parquet` which will be hosted in S3. Data sources can generally be files or tables in data warehouses.<br><br/> **Note**: data sources in Feast need timestamps for now. For data that doesn't change, unfortunately this will require you to supply a dummy timestamp.                                     |
| Entity                                                                          | The main entity we need here is a driver entity (with `driver_id` as the join key). Entities are used to construct composite keys to join feature views together. Typically, they map to the unique ids that you will have available at training / inference time.                                                                                                                                        |
| Feature view                                                                    | We'll have various feature views corresponding to different logical groups of features and transformations from data sources keyed on entities. These can be shared / re-used by data scientists and engineers and are registered with `feast apply`. <br><br/> Feast also supports reusable last mile transformations with `OnDemandFeatureView`s. We explore this  in [Module 2](../module_2/README.md) |
| Feature service                                                                 | We build different model versions with different sets of features using feature services (`model_v1`, `model_v2`). Feature services group features a given model version depends on. It allows retrieving all necessary model features by using a feature service name.                                                                                                                                   |
| Registry                                                                        | Where Feast tracks registered features, data sources, entities, feature services and metadata. Users + model servers will pull from this to discover registered features.<br></br> This is by default a single file which is not human readable (it's serialized protocol buffer). In the upcoming release, you can use SQLAlchemy to store this in a database like Postgres / MySQL.                     |
| Provider                                                                        | We use the AWS provider here. A provider is a customizable interface that Feast uses to orchestrate feature generation / retrieval. <br></br>Specifying a built-in provider (e.g. `aws`) ensures your registry can be stored in S3 (and also specifies default offline / online stores)                                                                                                                   |
| Offline store                                                                   | What Feast will use to execute point in time joins (typically a data warehouse). Here we use `file`                                                                                                                                                                                                                                                                                                       |
| Online store                                                                    | Low-latency data store that Feast uses to power online inference. Feast ingests offline feature values and streaming features into the online store. In this module, we do not need one.                                                                                                                                                                                                                  |
## A quick primer on feature views
Let's look at a feature view we have in this module:
```python
driver_hourly_stats_view = FeatureView(
    name="driver_hourly_stats",
    description="Hourly features",
    entities=["driver"],
    ttl=timedelta(seconds=8640000000),
    schema=[
        Field(name="conv_rate", dtype=Float32),
        Field(name="acc_rate", dtype=Float32),
    ],
    online=True,
    source=driver_stats,
    tags={"production": "True"},
    owner="test2@gmail.com",
)
```

Feature views are one of the most important concepts in Feast.

They represent a group of features that should be physically colocated (e.g. in the offline or online stores). More specifically:
- The above feature view comes from a single batch source (a `FileSource`). 
- If we wanted to also use an online store, the above feature view would be colocated in e.g. a Redis hash or a DynamoDB table. 
- A common need is to have both a batch and stream source for a single set of features. You'd thus have a `FeatureView` that essentially can have two different sources but map to the same physical location in the online store.

It's worth noting that there are multiple types of feature views. `OnDemandFeatureView`s for example enable row-level transformations on data sources and request data, with the output features described in the `schema` parameter.

# User groups
There are three user groups here worth considering. The ML platform team, the ML engineers running batch inference on models, and the data scientists building models. 

## User group 1: ML Platform Team
The team here sets up the centralized Feast feature repository and CI/CD in GitHub. 

### Step 0 (MinIO): Setup S3 bucket for registry and file sources

**Prerequisites**

* You have already installed `Kubeflow<https://elements-of-ai.github.io/kubeflow-docs/install/ubuntu.html>`_ on your cluster.

* You have installed `MinIO <https://min.io/docs/minio/kubernetes/upstream/index.html>`_  operator.

* You can access the kubeflow dashboard.

* You Have created Kubeflow Notebook refer to :ref:`user-guide-notebooks`.


Firstly you need to get MinIO access and secret key for authentication.

```bash

    # get the Minio secret name
    $ microk8s kubectl get secret -n admin | grep minio

    # get the access key for MinIO
    $ microk8s kubectl get secret <minio-secret-name> -n admin -o jsonpath='{.data.accesskey}' | base64 -d

    # get the secret key for MinIO
    $ microk8s kubectl get secret <minio-secret-name> -n admin -o jsonpath='{.data.secretkey}' | base64 -d
```

Secondly update the MinIO parameters on your environment, create a bucket for feast and upload data files to bucket.

```python

import os
from urllib.parse import urlparse
import boto3

# Update these parameters about your environment
os.environ["FEAST_S3_ENDPOINT_URL"] = "http://minio.kubeflow:9000"
os.environ["AWS_ACCESS_KEY_ID"] = "minio"
os.environ["AWS_SECRET_ACCESS_KEY"] = "RL4YSFL8TT39BBHZO7SKNYOG6Y5TDD"

s3 = boto3.resource('s3',
                    endpoint_url=os.getenv("MLFLOW_S3_ENDPOINT_URL"),
                    verify=False)

# Create a bucket
bucket_name='featurestore'
s3.create_bucket(Bucket=bucket_name)

# Check if the newly bucket exists
print(list(s3.buckets.all()))

# Upload data file to the newly bucket
bucket = s3.Bucket(bucket_name)
bucket_path = "infra"
bucket.upload_file("infra/driver_stats.parquet", os.path.join(bucket_path, "driver_stats.parquet"))

# check files
for obj in bucket.objects.filter(Prefix=bucket_path):
    print(obj.key)
```

### Step 1: Setup the feature repo
The first thing a platform team needs to do is setup a `feature_store.yaml` file within a version controlled repo like GitHub. `feature_store.yaml` is the primary way to configure an overall Feast project. We've setup a sample feature repository in `01_feature_repo_local/` and `02_feature_repo_s3_offline/` and `03_feature_repo_s3_offline_sqlit_online/`

#### Step 1a: Use your configured bucket

**data_sources.py**
```python
# MinIO
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
```

**feature_store.yaml**
```yaml
# MinIO
project: feast_demo_minio
provider: local
registry: s3://featurestore/infra/registry.pb # TODO: Replace with your bucket
online_store:
  type: sqlite
  path: data/online_store.db
offline_store:
  type: file
entity_key_serialization_version: 2
```

A quick explanation of what's happening in this `feature_store.yaml`:

| Key             | What it does                                                                         | Example                                                                                                  |
| :-------------- | :----------------------------------------------------------------------------------- | :------------------------------------------------------------------------------------------------------- |
| `project`       | Gives infrastructure isolation via namespacing (e.g. online stores + Feast objects). | any unique name within your organization (e.g. `feast_demo_aws`)                                         |
| `provider`      | Defines registry location & sets defaults for offline / online stores                | `gcp` enables a GCS-based registry and sets BigQuery + Datastore as the default offline / online stores. |
| `registry`      | Defines the specific path for the registry (local, gcs, s3, etc)                     | `s3://[YOUR BUCKET]/registry.pb`                                                                         |
| `online_store`  | Configures online store (if needed for supporting real-time models)                  | `null`, `redis`, `dynamodb`, `datastore`, `postgres`, `hbase` (each have their own extra configs)        |
| `offline_store` | Configures offline store, which executes point in time joins                         | `bigquery`, `snowflake.offline`,  `redshift`, `spark`, `trino`  (each have their own extra configs)      |
| `flags`         | (legacy) Soon to be deprecated way to enable experimental functionality.             |                                                                                                          |

#### Some further notes and gotchas
- **Project**
  - Users can only request features from a single project
- **Provider**
  - Default offline or online store choices can be easily overriden in `feature_store.yaml`. 
    - For example, one can use the `aws` provider and specify Snowflake as the offline store:
      ```yaml
      project: feast_demo_aws
      provider: aws
      registry: s3://[INSERT YOUR BUCKET]/registry.pb
      online_store: null
      offline_store:
          type: snowflake.offline
          account: SNOWFLAKE_DEPLOYMENT_URL
          user: SNOWFLAKE_USER
          password: SNOWFLAKE_PASSWORD
          role: SNOWFLAKE_ROLE
          warehouse: SNOWFLAKE_WAREHOUSE
          database: SNOWFLAKE_DATABASE
      ```
- **Offline store** 
  - We recommend users use data warehouses or Spark as their offline store for performant training dataset generation. 
    - In this workshop, we use file sources for instructional purposes. This will directly read from files (local or remote) and use Dask to execute point-in-time joins. 
  - A project can only support one type of offline store (cannot mix Snowflake + file for example)
  - Each offline store has its own configurations which map to YAML. (e.g. see [BigQueryOfflineStoreConfig](https://rtd.feast.dev/en/master/index.html#feast.infra.offline_stores.bigquery.BigQueryOfflineStoreConfig)):
- **Online store**
  - You only need this if you're powering real time models (e.g. inferring in response to user requests)
    - If you are precomputing predictions in batch (aka batch scoring), then the online store is optional. You should be using the offline store and running `feature_store.get_historical_features`. We touch on this later in this module.
  - Each online store has its own configurations which map to YAML. (e.g. [RedisOnlineStoreConfig](https://rtd.feast.dev/en/master/feast.infra.online_stores.html#feast.infra.online_stores.redis.RedisOnlineStoreConfig))
- **Custom offline / online stores** 
  - Generally, custom offline + online stores and providers are supported and can plug in. 
  - e.g. see [adding a new offline store](https://docs.feast.dev/how-to-guides/adding-a-new-offline-store), [adding a new online store](https://docs.feast.dev/how-to-guides/adding-support-for-a-new-online-store)
  - Example way of using a custom offline store you define:
    ```yaml
    project: test_custom
    registry: data/registry.db
    provider: local
    offline_store:
        type: feast_custom_offline_store.CustomOfflineStore
    ```

#### Step 1b: Run `feast plan`

With the `feature_store.yaml` setup, you can now run `feast plan` to see what changes would happen with `feast apply`.

```bash
feast plan
```

Sample output:
```console
$ feast plan

Created entity driver
Created feature view driver_hourly_stats
Created feature service model_v2
Created feature service model_v1

No changes to infrastructure
```

#### Step 1c: Run `feast apply`
Now run `feast apply`. 

This will parse the feature, data source, and feature service definitions and publish them to the registry. It may also setup some tables in the online store to materialize batch features to (in this case, we set the online store to null so no online store changes will occur). 

```console
$ feast apply

Created entity driver
Created feature view driver_hourly_stats
Created feature service model_v1
Created feature service model_v2

Deploying infrastructure for driver_hourly_stats
```

#### Step 1d: Verify features are registered
You can now run Feast CLI commands to verify Feast knows about your features and data sources.

```console
$ feast feature-views list

NAME                   ENTITIES    TYPE
driver_hourly_stats    {'driver'}  FeatureView
```

### Step 2: Setup a Web UI endpoint
Feast comes with an experimental Web UI. Users can already spin this up locally with `feast ui`, but you may want to have a Web UI that is universally available. Here, you'd likely deploy a service that runs `feast ui` on top of a `feature_store.yaml`, with some configuration on how frequently the UI should be refreshing its registry.

**Note**: If you're using Windows, you may need to run `feast ui -h localhost` instead.

```console
$ feast ui

INFO:     Started server process [10185]
05/15/2022 04:35:58 PM INFO:Started server process [10185]
INFO:     Waiting for application startup.
05/15/2022 04:35:58 PM INFO:Waiting for application startup.
INFO:     Application startup complete.
05/15/2022 04:35:58 PM INFO:Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8888 (Press CTRL+C to quit)
05/15/2022 04:35:58 PM INFO:Uvicorn running on http://0.0.0.0:8888 (Press CTRL+C to quit)
```
![Feast UI](sample_web_ui.png)
