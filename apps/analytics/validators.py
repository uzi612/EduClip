"""Chart.js payload validation (CHARTS-04): block malformed graphs before `ready`.

ChartValidator.validate(graphs) raises ChartValidationError describing the
exact path (e.g. graphs.keyword_density.data.datasets[0].data) so pipeline
bugs surface loudly instead of shipping broken canvases.
"""


class ChartValidationError(ValueError):
    """Raised when a graphs payload does not match the Chart.js contract."""


REQUIRED_GRAPHS = {
    "keyword_density": "bar",
    "chapter_duration": "doughnut",
    "engagement_curve": "line",
}


class ChartValidator:
    @staticmethod
    def validate(graphs):
        if not isinstance(graphs, dict):
            raise ChartValidationError("graphs must be an object.")
        for key, expected_type in REQUIRED_GRAPHS.items():
            if key not in graphs:
                raise ChartValidationError(f"graphs.{key} is missing.")
            ChartValidator._validate_graph(key, graphs[key], expected_type)
        return True

    @staticmethod
    def _validate_graph(key, graph, expected_type):
        base = f"graphs.{key}"
        if not isinstance(graph, dict):
            raise ChartValidationError(f"{base} must be an object.")
        if graph.get("type") != expected_type:
            raise ChartValidationError(
                f"{base}.type must be {expected_type!r}, "
                f"got {graph.get('type')!r}.")
        data = graph.get("data")
        if not isinstance(data, dict):
            raise ChartValidationError(f"{base}.data must be an object.")
        labels = data.get("labels")
        datasets = data.get("datasets")
        if not isinstance(labels, list) or not labels:
            raise ChartValidationError(f"{base}.data.labels must be a non-empty array.")
        if not isinstance(datasets, list) or not datasets:
            raise ChartValidationError(f"{base}.data.datasets must be a non-empty array.")
        for i, ds in enumerate(datasets):
            path = f"{base}.data.datasets[{i}]"
            if not isinstance(ds, dict) or not isinstance(ds.get("data"), list):
                raise ChartValidationError(f"{path}.data must be an array.")
            if len(ds["data"]) != len(labels):
                raise ChartValidationError(
                    f"{path}.data length {len(ds['data'])} != labels length {len(labels)}.")
            if not all(isinstance(v, (int, float)) for v in ds["data"]):
                raise ChartValidationError(f"{path}.data must contain only numbers.")
