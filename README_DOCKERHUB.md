# pts-framework

Container image for [pypts](https://github.com/CERN/pts-framework), the hardware-oriented
testing framework developed by BE-CEM-MTA. It runs the pypts GUI inside the container and shows
it in your browser, so you only need Docker: no local Python, Qt or X server.

## Quick start

Save this as `docker-compose.yaml` and run `docker compose up`:

```yaml
services:
  pypts:
    image: cern/pts-framework:latest
    ports:
      - "127.0.0.1:6080:6080"
    volumes:
      - ./pts_reports:/home/pts/pts_reports
      - ./recipes:/recipes
```

Then open <http://localhost:6080/vnc.html?autoconnect=true&resize=scale>. The pypts window
appears in the browser tab. Use the folder icon to open a recipe: yours are in `/recipes`, the
bundled examples in `/home/pts/examples`. Reports are saved to `./pts_reports`.

Without Compose (nothing is saved outside the container):

```sh
docker run --rm -p 127.0.0.1:6080:6080 cern/pts-framework
```

* **Screen size:** set the `RESOLUTION` environment variable, for example `1280x800` (default
  `1920x1080`).
* **Security:** the display has no password, so keep `127.0.0.1` in the port mapping.
* **Linux:** mounted directories must be writable by UID 1000.

Validate a recipe without opening the GUI:

```sh
docker run --rm -v "$PWD":/work -w /work cern/pts-framework python -m pypts.validate_recipe my_recipe.yml
```

## Tags

| Tag | Meaning |
| --- | --- |
| `latest` | The most recent release. |
| `X.Y.Z` | An exact release, for example `0.6.2`. |
| `X.Y` | The most recent patch release of that minor version. |
| `X` | The most recent release of that major version (published from `1.0.0` onwards). |
| `edge` | The latest commit on `master`, which may be unreleased. |
| `sha-<commit>` | A specific commit, identified by its first 7 characters. |

Pin an `X.Y.Z` or `sha-<commit>` tag when you need reproducible runs. `latest`, `X.Y`, `X` and
`edge` move as new versions are published.

## Links

* [Documentation](https://cern.github.io/pts-framework/)
* [Source code](https://github.com/CERN/pts-framework)
* Licence: LGPL-2.1-or-later
