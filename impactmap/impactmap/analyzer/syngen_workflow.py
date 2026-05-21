"""
syngen_workflow.py
------------------
Orchestrates the end-to-end synthetic data generation workflow.

Calls SyngenClient methods in sequence and reports progress
via a callback function for each step. Designed to run in a
background thread so the UI can update incrementally.
"""

import time
from datetime import datetime
from typing import Callable

from syngen_client import SyngenClient, SyngenError

# Status constants
RUNNING = "running"
DONE = "done"
ERROR = "error"

STEP_DELAY = 2  # seconds between steps


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def run_syngen_workflow(
    client: SyngenClient,
    jdbc_driver_id: str,
    db_host: str,
    db_port: int,
    db_user: str,
    db_password: str,
    db_name: str,
    db_schema: str,
    tables: list[str],
    on_message: Callable[[str, str], None],
):
    """
    Execute the full synthetic data generation workflow.

    Args:
        client: Configured SyngenClient instance.
        jdbc_driver_id: ID of the pre-uploaded PostgreSQL JDBC driver file.
        db_host: Hostname for the proxy-app database (as seen by syngen-api).
        db_port: Port for the proxy-app database.
        db_user: Database username.
        db_password: Database password.
        db_name: Database name.
        db_schema: Database schema name.
        tables: List of table names to generate data for.
        on_message: Callback(text, status) to report progress.
    """

    try:
        table_list = ", ".join(tables)

        # ── Initiate ─────────────────────────────────────────
        on_message("Initiating Data Generation...", RUNNING)
        # time.sleep(STEP_DELAY)

        # ── Step 1: Search for application ───────────────────
        on_message("Checking for application availability...", RUNNING)
        # time.sleep(STEP_DELAY)
        apps = client.search_applications("Amazone")
        if apps:
            app_id = apps[0]["id"]
            on_message(f"Application found: **Amazone** (id: {app_id[:8]}...)", DONE)
        else:
            on_message("Application not found. Adding application...", RUNNING)
            # time.sleep(STEP_DELAY)
            resp = client.create_application(
                "Amazone", "TestMeridian proxy e-commerce app"
            )
            app_id = resp["id"]
            on_message(f"Application created: **Amazone** (id: {app_id[:8]}...)", DONE)

        # time.sleep(STEP_DELAY)

        # ── Step 2: Search for connector ─────────────────────
        on_message("Checking for existing database connector...", RUNNING)
        # time.sleep(STEP_DELAY)
        connectors = client.search_connectors(app_id)
        ref_connectors = [c for c in connectors if c.get("is_reference")]
        if ref_connectors:
            connector_id = ref_connectors[0]["id"]
            on_message(f"Connector found: **{ref_connectors[0].get('name', 'Amazone-DB')}**", DONE)
        else:
            # ── Register JDBC driver if needed ───────────────
            on_message("Checking for PostgreSQL JDBC driver...", RUNNING)
            # time.sleep(STEP_DELAY)
            drivers = client.search_jdbc_drivers()
            pg_drivers = [
                d for d in drivers
                if "postgresql" in (d.get("name", "") + d.get("driver_class_name", "")).lower()
            ]
            if pg_drivers:
                driver_id = pg_drivers[0]["id"]
                on_message("PostgreSQL JDBC driver found.", DONE)
            else:
                on_message("Registering PostgreSQL JDBC driver...", RUNNING)
                # time.sleep(STEP_DELAY)
                driver_resp = client.register_jdbc_driver(
                    name="PostgreSQL JDBC Driver",
                    driver_class_name="org.postgresql.Driver",
                    file_upload_id=jdbc_driver_id,
                )
                driver_id = driver_resp["id"]
                on_message("JDBC driver registered.", DONE)

            # time.sleep(STEP_DELAY)

            # ── Create connector ─────────────────────────────
            on_message("Creating database connector...", RUNNING)
            # time.sleep(STEP_DELAY)
            conn_resp = client.create_connector(
                name="Amazone-DB",
                app_id=app_id,
                jdbc_driver_id=driver_id,
                host=db_host,
                port=db_port,
                username=db_user,
                password=db_password,
                database_name=db_name,
                schema_name=db_schema,
            )
            connector_id = conn_resp["id"]
            on_message("Connector created: **Amazone-DB**", DONE)

        # time.sleep(STEP_DELAY)

        # ── Step 3: Sync application ─────────────────────────
        on_message("Triggering schema discovery...", RUNNING)
        # time.sleep(STEP_DELAY)
        client.sync_application(app_id)
        on_message("Discovery job started. Waiting for completion...", RUNNING)

        # ── Poll sync status ─────────────────────────────────
        for attempt in range(60):  # max 3 minutes
            time.sleep(3)
            app = client.get_application(app_id)
            status = app.get("sync_status", "")
            if status == "ACTIVE":
                on_message("Schema discovery complete.", DONE)
                break
            elif status == "ERROR":
                raise SyngenError("Schema discovery failed. Check syngen-api logs.")
            elif attempt % 3 == 0:  # update every ~9 seconds
                on_message(f"Still discovering... (status: {status})", RUNNING)
        else:
            raise SyngenError("Schema discovery timed out after 3 minutes.")

        # time.sleep(STEP_DELAY)

        # ── Step 4: Find structures ──────────────────────────
        on_message(f"Finding structures for tables: **{table_list}**", RUNNING)
        # time.sleep(STEP_DELAY)
        all_structures = client.search_structures(app_id)
        matched = [
            s for s in all_structures
            if s.get("name", "").lower() in {t.lower() for t in tables}
        ]
        if not matched:
            raise SyngenError(f"No structures found matching tables: {table_list}")
        matched_names = [s["name"] for s in matched]
        structure_ids = [s["id"] for s in matched]
        on_message(f"Found {len(matched)} structures: **{', '.join(matched_names)}**", DONE)

        # time.sleep(STEP_DELAY)

        # ── Step 5: Create dataset ───────────────────────────
        dataset_name = f"TestData-{int(time.time())}"
        on_message(f"Creating dataset: **{dataset_name}**", RUNNING)
        # time.sleep(STEP_DELAY)
        ds_resp = client.create_dataset(
            name=dataset_name,
            app_id=app_id,
            description=f"Synthetic test data for tables: {table_list}",
        )
        dataset_id = ds_resp["id"]
        on_message("Dataset created.", DONE)

        # time.sleep(STEP_DELAY)

        # ── Step 6: Pull structures ──────────────────────────
        on_message("Pulling table structures into dataset...", RUNNING)
        # time.sleep(STEP_DELAY)
        client.pull_structures(dataset_id, structure_ids, include_dependents=True)
        on_message("Structures pulled (including dependent tables).", DONE)

        # time.sleep(STEP_DELAY)

        # ── Step 6b: Patch UUID primary key fields ─────────────
        on_message("Configuring UUID primary key fields...", RUNNING)
        # time.sleep(STEP_DELAY)
        ds_fields = client.get_dataset_fields(dataset_id)
        uuid_pk_fields = [
            f for f in ds_fields
            if f.get("is_primary_key")
            and (
                str(f.get("sql_type", "")).lower() in ("uuid", "object", "other", "1111")
                or str(f.get("display_type", "")).lower() in ("uuid", "object", "other")
                or f.get("name", "").lower() == "id"
            )
        ]
        UUID_GENERATOR_INSTANCE_ID = "8b59c0e6-10ca-41fb-bbe4-0d14a74fb421"
        if uuid_pk_fields:
            for field in uuid_pk_fields:
                client.patch_field(dataset_id, str(field["id"]), {
                    "generator_id": UUID_GENERATOR_INSTANCE_ID,
                })
            on_message(f"Configured {len(uuid_pk_fields)} UUID primary key field(s) with UUID generator.", DONE)
        else:
            on_message("No UUID primary key fields to configure.", DONE)

        # time.sleep(STEP_DELAY)

        # ── Step 7: Set records count ────────────────────────
        on_message("Setting record count to 1 per table...", RUNNING)
        # time.sleep(STEP_DELAY)
        ds_structures = client.get_dataset_structures(dataset_id)
        overrides = [
            {"structure_id": s["id"], "records_count": 1} for s in ds_structures
        ]
        if overrides:
            client.update_records_count(dataset_id, overrides)
        on_message("Record counts configured.", DONE)

        # time.sleep(STEP_DELAY)

        # ── Step 8: Create job ───────────────────────────────
        job_name = f"TestData-Gen-{int(time.time())}"
        on_message("Creating synthetic data generation job...", RUNNING)
        # time.sleep(STEP_DELAY)
        job_resp = client.create_job(
            name=job_name,
            dataset_id=dataset_id,
            reference_connector_id=connector_id,
            target_connector_id=connector_id,
        )
        job_id = job_resp["id"]
        on_message("Job created. Starting execution...", DONE)

        # time.sleep(STEP_DELAY)

        # ── Step 9: Execute job ──────────────────────────────
        on_message("Executing synthetic data generation...", RUNNING)
        exec_resp = client.create_execution(job_id)
        execution_id = exec_resp["id"]

        # ── Poll execution status ────────────────────────────
        for attempt in range(120):  # max 6 minutes
            time.sleep(3)
            ex = client.get_execution(execution_id)
            ex_status = ex.get("status", "")
            progress = ex.get("progress", 0)
            if ex_status == "SUCCESS":
                on_message(
                    f"Synthetic data generated successfully! "
                    f"1 record created in: **{table_list}**",
                    DONE,
                )
                on_message(
                    "You can now run your test scenario against the database. "
                    "Ask me if you have any questions!",
                    DONE,
                )
                return
            elif ex_status in ("FAILURE", "CANCELLED"):
                raise SyngenError(f"Job execution {ex_status.lower()}.")
            elif attempt % 3 == 0:
                on_message(f"Generating... ({progress}% complete)", RUNNING)
        raise SyngenError("Job execution timed out after 6 minutes.")

    except SyngenError as e:
        on_message(f"Error: {e}", ERROR)
    except Exception as e:
        on_message(f"Unexpected error: {e}", ERROR)
