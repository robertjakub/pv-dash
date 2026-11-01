const SOLAR_CONFIG = {
  prometheusUrl: '/prom',
  metrics: {
    pv: 'huawei_pv_generation_watts{job="sun2000"}',
    gridExport: 'huawei_grid_export_watts{job="sun2000"}',
    gridImport: 'huawei_grid_import_watts{job="sun2000"}',
    load: 'huawei_home_consumption_watts{job="sun2000"}'
  },
  scrapeSec: 10,
  smoothMin: 30,
  refreshSec: 30,
  defaultLang: 'en',
  enableAllTime: false
};
