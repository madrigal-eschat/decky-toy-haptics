import {
  ButtonItem,
  PanelSection,
  PanelSectionRow,
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
const getStatus = callable<[], { running: boolean; connected: boolean; port: number }>('get_status');
const getDevices = callable<[], { id: number; name: string; actuators: number }[]>('get_devices');
const setBridgeEnabled = callable<[boolean], { success: boolean }>('set_bridge_enabled');
const listEvdevDevices = callable<[], { device: string; name: string; path: string }[]>('list_evdev_devices');
const setBridgeScale = callable<[number], { success: boolean }>('set_bridge_scale');

type DeviceInfo = { id: number; name: string; actuators: number };
type EngineStatus = { running: boolean; connected: boolean; port: number };
type EvdevDevice = { device: string; name: string; path: string };

function Content() {
  const [status, setStatus] = useState<EngineStatus>({
    running: false,
    connected: false,
    port: 12345,
  });
  const [devices, setDevices] = useState<DeviceInfo[]>([]);
  const [loading, setLoading] = useState(false);
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

  return (
    <>
      <PanelSection title="Toy Haptics">
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={handleToggle} disabled={loading}>
            {loading ? 'Working…' : status.running ? 'Stop Engine' : 'Start Engine'}
          </ButtonItem>
        </PanelSectionRow>
        {error && (
          <PanelSectionRow>
            <div style={{ color: '#f88', fontSize: '12px' }}>{error}</div>
          </PanelSectionRow>
        )}
        <PanelSectionRow>
          <div style={{ fontSize: '12px', color: status.connected ? '#8f8' : '#888' }}>
            {status.connected
              ? `Connected · port ${status.port}`
              : 'Disconnected'}
          </div>
        </PanelSectionRow>
      </PanelSection>

      <BridgePanel />

      <PanelSection title="Devices">
        {devices.length === 0 ? (
          <PanelSectionRow>
            <div style={{ fontSize: '12px', color: '#888' }}>No devices connected</div>
          </PanelSectionRow>
        ) : (
          devices.map(dev => (
            <PanelSectionRow key={dev.id}>
              <div style={{ fontSize: '13px' }}>{dev.name}</div>
            </PanelSectionRow>
          ))
        )}
      </PanelSection>
    </>
  );
}

function BridgePanel() {
  const [enabled, setEnabled] = useState(false);
  const [scale, setScale] = useState(1.0);
  const [devices, setDevices] = useState<EvdevDevice[]>([]);
  const [loading, setLoading] = useState(false);

  const refreshDevices = async () => {
    const d = await listEvdevDevices();
    if (d) setDevices(d);
  };

  useEffect(() => {
    refreshDevices();

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
    try {
      await setBridgeEnabled(!enabled);
      setEnabled(e => !e);
      if (!enabled) await refreshDevices();
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
        <div style={{ fontSize: '12px', color: enabled ? '#8f8' : '#888' }}>
          {enabled ? 'Active' : 'Inactive'}
        </div>
      </PanelSectionRow>
      {devices.length > 0 && (
        <>
          <PanelSectionRow>
            <div style={{ fontSize: '11px', color: '#aaa', marginTop: 4 }}>Source Devices</div>
          </PanelSectionRow>
          {devices.map(d => (
            <PanelSectionRow key={d.device}>
              <div style={{ fontSize: '12px' }}>
                <span style={{ color: '#ccc' }}>{d.device}</span>
                {' '}{d.name}
                <br />
                <span style={{ fontSize: '11px', color: '#888' }}>→ All toys</span>
              </div>
            </PanelSectionRow>
          ))}
        </>
      )}
      <PanelSectionRow>
        <div style={{ fontSize: '12px' }}>Intensity Scale</div>
        <input
          type="range" min={0} max={1} step={0.05}
          value={scale}
          onChange={e => handleScale(parseFloat(e.target.value))}
          style={{ width: '100%' }}
        />
        <div style={{ fontSize: '11px', color: '#aaa', textAlign: 'right' }}>
          {(scale * 100).toFixed(0)}%
        </div>
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
    },
  };
});
