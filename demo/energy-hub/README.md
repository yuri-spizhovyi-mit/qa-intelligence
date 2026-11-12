# Demo Energy Hub

A fictional energy-event application under test for QA Intelligence M3. It has two synchronous business endpoints and a browser page for submitting raw JSON and retrieving an event.

## Start

Run from the repository root:

```text
docker compose -p qi-m1-foundation --profile demo up -d --build demo
```

Open `http://localhost:8002/` for the page or `http://localhost:8002/docs` for the API contract. QA Intelligence remains at port 8000.

The demo uses the pinned Python base and shared runtime dependency lock. It runs as UID/GID 10001 with a read-only root, writable temporary directory, dropped capabilities and CPU/memory/process limits. Its dedicated bridge network is separate from the platform network. It has no host mounts, persistent volume or credentials.

The browser-accessible demo network has normal Docker bridge connectivity. Restricted generated-test networking and runner controls are a subsequent M3 increment.

## Use

1. Click **Submit event** to send the sample JSON. A new event returns 201, a Location header and the normalized event.
2. Click **Retrieve event** to fetch the event by ID.
3. Submit the same JSON again for an equivalent replay with 200.
4. Change its energy value while keeping the ID for a conflict with 409.
5. Enter `10.0`, `"10"`, or an out-of-range energy value for a 422 response.
6. Click **New sample** to prepare another event with an unused ID.

The page sends the textarea contents unchanged, preserving the difference between JSON `10` and `10.0`. Event responses and errors are displayed as text.

## Data lifetime and input policy

Events are held in memory by a single API process and disappear on restart. The platform's saved analyses and reviews use separate durable storage.

Only the four documented event fields are accepted. Timestamps require an explicit offset, seconds from 00 through 59, and at most six fractional digits, matching the fixture's datetime representation. Responses normalize them to UTC with a Z suffix. See the [event specification](../../docs/demo-energy-hub.md).

## Verification

After exact-file human review, 31 API/page scenarios passed in a verified network-disabled, non-root, read-only container with no mounts or credentials and bounded resources. They include strict inputs, boundaries, replay/conflict behavior, normalization, concurrent equivalent submissions and fresh-instance reset.

Browser interaction verified new submission, retrieval, replay and strict rejection of raw decimal JSON. An actual container restart changed retrieval of an existing event from 200 to 404. The platform's approved analysis remained available.

These checks establish the owned test target. Generated executable artifacts and their runner are introduced separately.
