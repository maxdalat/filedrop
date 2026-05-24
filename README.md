# filedrop

Minimal Flask webpage plus API server, packaged with Docker. Files upload into the local `uploads/` folder inside the running app/container.

## Run with Docker

```sh
docker build -t filedrop .
docker run --rm -p 8000:8000 filedrop
```

Open <http://localhost:8000>.

API checks:

```sh
curl http://localhost:8000/api/health
curl http://localhost:8000/api/files
curl -F "file=@example.txt" http://localhost:8000/api/files
curl -O http://localhost:8000/api/files/example.txt
```
