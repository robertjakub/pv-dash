const SOLAR_CONFIG = {
  prometheusUrl: '/prom',
  battery: false,               // enable battery support (Battery node + energy split)
  metrics: {
    pv: 'huawei_pv_generation_watts{job="sun2000"}',
    gridExport: 'huawei_grid_export_watts{job="sun2000"}',
    gridImport: 'huawei_grid_import_watts{job="sun2000"}',
    load: 'huawei_home_consumption_watts{job="sun2000"}',
    battery: 'huawei_battery_net_watts{job="sun2000"}',
    batterySoC: 'huawei_battery_soc_percent{job="sun2000"}',
    batteryFlag: 'huawei_battery{job="sun2000"}'
  },
  scrapeSec: 10,
  smoothMin: 30,
  refreshSec: 30,
  defaultLang: 'en',
  enableAllTime: false
};
