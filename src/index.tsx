import {
  ButtonItem,
  Focusable,
  PanelSection,
  PanelSectionRow,
  SliderField,
  staticClasses,
} from '@decky/ui';
import {
  addEventListener,
  removeEventListener,
  callable,
  definePlugin,
} from '@decky/api';
import { useState, useEffect } from 'react';
import { FaHeart } from 'react-icons/fa';

const startEngine = callable<[], { success: boolean; error?: string }>('start_engine');
const stopEngine = callable<[], { success: boolean }>('stop_engine');
const getStatus = callable<[], {
  running: boolean; connected: boolean; scanning: boolean; port: number;
  bridge_enabled: boolean; bridge_running: boolean; bridge_scale: number;
}>('get_status');
const getDevices = callable<[], { id: number; name: string; actuators: number }[]>('get_devices');
const setBridgeEnabled = callable<[boolean], { success: boolean; error?: string }>('set_bridge_enabled');
const listEvdevDevices = callable<[], { device: string; name: string; path: string }[]>('list_evdev_devices');
const setBridgeScale = callable<[number], { success: boolean }>('set_bridge_scale');
const startScan = callable<[], { success: boolean; error?: string }>('start_scan');
const stopScan = callable<[], { success: boolean }>('stop_scan');

type DeviceInfo = { id: number; name: string; actuators: number };
type EngineStatus = { running: boolean; connected: boolean; scanning: boolean; port: number };
type EvdevDevice = { device: string; name: string; path: string };

function Content() {
  const [status, setStatus] = useState<EngineStatus>({
    running: false,
    connected: false,
    scanning: false,
    port: 12345,
  });
  const [devices, setDevices] = useState<DeviceInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [scanLoading, setScanLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refreshStatus = async () => {
    const s = await getStatus();
    if (s) setStatus(s);
  };

  const refreshDevices = async () => {
    const d = await getDevices();
    if (d) setDevices(d);
  };

  useEffect(() => {
    refreshStatus();
    refreshDevices();

    const onStatusChanged = () => void refreshStatus();
    const onDevicesChanged = () => void refreshDevices();

    window.addEventListener('intiface:status_changed', onStatusChanged);
    window.addEventListener('intiface:devices_changed', onDevicesChanged);

    return () => {
      window.removeEventListener('intiface:status_changed', onStatusChanged);
      window.removeEventListener('intiface:devices_changed', onDevicesChanged);
    };
  }, []);

  const handleToggle = async () => {
    setLoading(true);
    setError(null);
    try {
      if (status.running) {
        await stopEngine();
      } else {
        const result = await startEngine();
        if (!result.success && result.error) {
          setError(result.error);
        }
      }
    } finally {
      setLoading(false);
    }
  };

  const handleScanToggle = async () => {
    setScanLoading(true);
    try {
      if (status.scanning) {
        await stopScan();
      } else {
        await startScan();
      }
    } finally {
      setScanLoading(false);
    }
  };

  return (
    <>
      <PanelSection title="Toy Haptics">
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={handleToggle} disabled={loading}>
            {loading ? 'Working…' : status.running ? 'Stop Engine' : 'Start Engine'}
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <Focusable style={{ fontSize: '11px', color: '#888' }}>
            Some toys need this order: start the engine, scan, turn the toy on, then restart the engine.
          </Focusable>
        </PanelSectionRow>
        {error && (
          <PanelSectionRow>
            <Focusable style={{ color: '#f88', fontSize: '12px' }}>{error}</Focusable>
          </PanelSectionRow>
        )}
        <PanelSectionRow>
          <Focusable style={{ fontSize: '12px', color: status.connected ? '#8f8' : '#888' }}>
            {status.connected
              ? `Connected · port ${status.port}`
              : 'Disconnected'}
          </Focusable>
        </PanelSectionRow>
        {status.connected && (
          <>
            <PanelSectionRow>
              <ButtonItem layout="below" onClick={handleScanToggle} disabled={scanLoading}>
                {scanLoading ? 'Working…' : status.scanning ? 'Stop Scanning' : 'Scan for Toys'}
              </ButtonItem>
            </PanelSectionRow>
            <PanelSectionRow>
              <Focusable style={{ fontSize: '12px', color: status.scanning ? '#8f8' : '#888' }}>
                {status.scanning ? 'Scanning…' : 'Not scanning'}
              </Focusable>
            </PanelSectionRow>
          </>
        )}
      </PanelSection>

      <PanelSection title="Devices">
        {devices.length === 0 ? (
          <PanelSectionRow>
            <Focusable style={{ fontSize: '12px', color: '#888' }}>No devices connected</Focusable>
          </PanelSectionRow>
        ) : (
          devices.map(dev => (
            <PanelSectionRow key={dev.id}>
              <Focusable style={{ fontSize: '13px' }}>{dev.name}</Focusable>
            </PanelSectionRow>
          ))
        )}
      </PanelSection>

      <BridgePanel />
    </>
  );
}

function BridgePanel() {
  const [enabled, setEnabled] = useState(false);
  const [scale, setScale] = useState(1.0);
  const [devices, setDevices] = useState<EvdevDevice[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refreshDevices = async () => {
    const d = await listEvdevDevices();
    if (d) setDevices(d);
  };

  useEffect(() => {
    refreshDevices();

    (async () => {
      const s = await getStatus();
      if (s) {
        setEnabled(s.bridge_running);
        setScale(s.bridge_scale);
      }
    })();

    const onBridgeStatus = (_enabled: boolean, _device: string | null) => {
      setEnabled(_enabled);
      if (_enabled) void refreshDevices();
    };
    const listener = addEventListener<[boolean, string | null]>(
      'bridge_status_changed', onBridgeStatus
    );
    return () => removeEventListener('bridge_status_changed', listener);
  }, []);

  const handleToggle = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await setBridgeEnabled(!enabled);
      if (!result.success && result.error) {
        setError(result.error);
      }
      // enabled state itself is set by the bridge_status_changed listener,
      // which is the authoritative source and can race with this resolving
    } finally {
      setLoading(false);
    }
  };

  const handleScale = async (v: number) => {
    setScale(v);
    await setBridgeScale(v);
  };

  return (
    <PanelSection title="Haptics Bridge">
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={handleToggle} disabled={loading}>
          {loading ? 'Working…' : enabled ? 'Disable Bridge' : 'Enable Bridge'}
        </ButtonItem>
      </PanelSectionRow>
      <PanelSectionRow>
        <Focusable style={{ fontSize: '11px', color: '#888' }}>
          Restarting the bridge will require restarting most games to pick haptics back up.
        </Focusable>
      </PanelSectionRow>
      {error && (
        <PanelSectionRow>
          <Focusable style={{ color: '#f88', fontSize: '12px' }}>{error}</Focusable>
        </PanelSectionRow>
      )}
      <PanelSectionRow>
        <Focusable style={{ fontSize: '12px', color: enabled ? '#8f8' : '#888' }}>
          {enabled ? 'Active' : 'Inactive'}
        </Focusable>
      </PanelSectionRow>
      {devices.length > 0 && (
        <>
          <PanelSectionRow>
            <Focusable style={{ fontSize: '11px', color: '#aaa', marginTop: 4 }}>Source Devices</Focusable>
          </PanelSectionRow>
          {devices.map(d => (
            <PanelSectionRow key={d.device}>
              <Focusable style={{ fontSize: '12px' }}>
                <span style={{ color: '#ccc' }}>{d.device}</span>
                {' '}{d.name}
                <br />
                <span style={{ fontSize: '11px', color: '#888' }}>→ All toys</span>
              </Focusable>
            </PanelSectionRow>
          ))}
        </>
      )}
      <PanelSectionRow>
        <SliderField
          label="Intensity Scale"
          value={Math.round(scale * 100)}
          min={0}
          max={100}
          step={5}
          showValue
          valueSuffix="%"
          onChange={v => handleScale(v / 100)}
        />
      </PanelSectionRow>
    </PanelSection>
  );
}

export default definePlugin(() => {
  const engineStatusListener = addEventListener<
    [running: boolean, connected: boolean, port: number]
  >('engine_status_changed', () => {
    window.dispatchEvent(new CustomEvent('intiface:status_changed'));
  });

  const deviceAddedListener = addEventListener<[id: number, name: string, actuators: number]>(
    'device_added',
    (_id, _name, _actuators) => {
      window.dispatchEvent(new CustomEvent('intiface:devices_changed'));
    }
  );

  const deviceRemovedListener = addEventListener<[id: number]>(
    'device_removed',
    (_id) => {
      window.dispatchEvent(new CustomEvent('intiface:devices_changed'));
    }
  );

  const bridgeStatusListener = addEventListener<[boolean, string | null]>(
    'bridge_status_changed', () => {}
  );

  const scanStatusListener = addEventListener<[scanning: boolean]>(
    'scan_status_changed', () => {
      window.dispatchEvent(new CustomEvent('intiface:status_changed'));
    }
  );

  return {
    name: 'Toy Haptics',
    titleView: <div className={staticClasses.Title}>Toy Haptics</div>,
    content: <Content />,
    icon: <FaHeart />,
    onDismount() {
      removeEventListener('engine_status_changed', engineStatusListener);
      removeEventListener('device_added', deviceAddedListener);
      removeEventListener('device_removed', deviceRemovedListener);
      removeEventListener('bridge_status_changed', bridgeStatusListener);
      removeEventListener('scan_status_changed', scanStatusListener);
    },
  };
});
