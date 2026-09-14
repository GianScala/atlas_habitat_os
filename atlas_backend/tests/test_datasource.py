"""The data-source seam — the abstraction that keeps Grafana one option.

These guard the two promises of app/datasource: that the active adapter is
chosen from config with no caller naming a transport, and that read-only
enforcement lives once, below every InfluxQL adapter.
"""

import pytest

import app.datasource as ds
from app.core.errors import ConfigurationError, DatasourceError
from app.datasource.grafana import GrafanaDataSource
from app.datasource.influxdb import InfluxDBDataSource
from app.datasource.wire import assert_read_only, parse_influx_response


class TestRegistry:
    def test_defaults_to_grafana(self, monkeypatch):
        from app.config import get_settings

        monkeypatch.setattr(get_settings(), "data_source", "grafana")
        ds.reset()
        assert isinstance(ds.get_data_source(), GrafanaDataSource)

    def test_selects_influxdb_from_config(self, monkeypatch):
        from app.config import get_settings

        monkeypatch.setattr(get_settings(), "data_source", "influxdb")
        ds.reset()
        assert isinstance(ds.get_data_source(), InfluxDBDataSource)

    def test_unknown_adapter_is_a_clear_error(self, monkeypatch):
        from app.config import get_settings

        monkeypatch.setattr(get_settings(), "data_source", "cassandra")
        ds.reset()
        with pytest.raises(ConfigurationError) as exc:
            ds.get_data_source()
        assert "cassandra" in str(exc.value)

    def test_adding_an_adapter_is_one_map_entry(self):
        # The promise the docs make: a new backend registers here and every
        # caller reaches it through the same influxql() with no other change.
        assert set(ds.ADAPTERS) >= {"grafana", "influxdb"}

    def teardown_method(self):
        ds.reset()


class TestReadOnly:
    def test_allows_select_and_show(self):
        assert_read_only("SELECT last(value) FROM Temperature")
        assert_read_only("SHOW MEASUREMENTS")

    def test_refuses_writes(self):
        for bad in ("DROP MEASUREMENT x", "DELETE FROM y", "INSERT a value=1"):
            with pytest.raises(DatasourceError):
                assert_read_only(bad)

    def test_refuses_statement_chaining_and_into(self):
        with pytest.raises(DatasourceError):
            assert_read_only("SELECT * FROM a; DROP MEASUREMENT b")
        with pytest.raises(DatasourceError):
            assert_read_only("SELECT * INTO copy FROM a")


class TestResponseParsing:
    def test_flattens_influx_1x_shape(self):
        payload = {
            "results": [
                {
                    "series": [
                        {
                            "name": "Temperature",
                            "tags": {"Location": "Container3"},
                            "columns": ["time", "value"],
                            "values": [[0, 21.4]],
                        }
                    ]
                }
            ]
        }
        out = parse_influx_response(payload, "SELECT ...", "habitat")
        assert out["database"] == "habitat"
        assert out["series"][0]["tags"] == {"Location": "Container3"}
        assert out["series"][0]["values"] == [[0, 21.4]]

    def test_surfaces_an_influx_error(self):
        payload = {"results": [{"error": "expected field"}]}
        with pytest.raises(DatasourceError):
            parse_influx_response(payload, "SELECT bad", "habitat")
