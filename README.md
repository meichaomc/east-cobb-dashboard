# East Cobb housing and macro dashboard

A personal dashboard of macro and East Cobb (Marietta, GA) housing data.

- `fetch_data.py` downloads the data into `data/`.
- `build_site.py` combines `index.html`, `standalone/` and `data/` into `site/index.html`.
- `.github/workflows/refresh.yml` runs both every day and publishes the page to GitHub Pages.

Data comes from FRED (St. Louis Fed), Realtor.com, Zillow, Indeed and the Cleveland Fed. Each source keeps its own rights and terms. This is for personal reference and is not financial advice.
