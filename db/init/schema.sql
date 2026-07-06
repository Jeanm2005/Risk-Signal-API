Create Table if not Exists companies (
    id       Serial Primary Key,
    ticker   Varchar(16) unique
);

Create Table if not Exists api_keys (
    id              Serial Primary Key,
    key_hash        Varchar(64) not Null unique,
    owner           Varchar(100),
    requests_per_hour   Integer default 100,
    created_at      Timestamptz default now(),
    last_used_at    Timestamptz,
    active          Boolean default true
);

Create Table if not Exists prediction_logs (
    id                      Serial Primary Key,
    company_id              Integer References companies(id),
    predicted_at            Timestamptz default now(),
    model_version           Varchar(50) not Null,
    input_features          JSONB not Null,
    output_score            Double Precision not Null,
    confidence              Double Precision,
    feature_contributions   JSONB,
    runtime_ms              Integer,
    inference_backend       Varchar(20)
);

Insert into api_keys (key_hash, owner)
Values ('6a6be91067e41184a08f010d33f30039a06212edde6df7b753f7b704fe526adf', 'container-demo')
On Conflict (key_hash) Do Nothing;