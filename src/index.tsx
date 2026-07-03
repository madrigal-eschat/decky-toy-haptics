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
import { FaHeart, FaVolumeUp, FaPowerOff } from 'react-icons/fa';

const startEngine = callable<[], { success: boolean; error?: string }>('start_engine');
const stopEngine = callable<[], { success: boolean }>('stop_engine');
const getStatus = callable<[], { running: boolean; connected: boolean; port: number }>('get_status');
const getDevices = callable<[], { id: number; name: string; actuators: number }[]>('get_devices');
const setBridgeEnabled = callable<[enabled: boolean], { success: boolean }>('set_bridge_enabled');
const setBridgeScale = callable<[scale: number], { success: boolean }>('set_bridge_scale');
const setBridgeDeviceMap = callable<[map: { [key: string]: number[] }], { success: boolean }>('set_bridge_device_map');

type DeviceInfo = { id: number; name: string; actuators: number };
type EngineStatus = { running: boolean; connected: boolean; port: number; bridge_enabled: boolean; bridge_scale: number; bridge_device_map: { [key: string]: number[] } };

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

  const handleSetDeviceMap = async (map: { [key: string]: number[] }) => {
    setLoading(true);
    setError(null);
    try {
      const result = await setBridgeDeviceMap({ map });
      if (result.success) {
        window.dispatchEvent(new CustomEvent('intiface:status_changed'));
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

      <PanelSection title="Haptics Bridge">
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={async () => {
              const result = await setBridgeEnabled(!status.bridge_enabled);
              refreshStatus();
            }}
          >
            <FaPowerOff style={{ marginRight: '8px' }} />
            {status.bridge_enabled ? 'Disable Bridge' : 'Enable Bridge'}
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <div style={{ fontSize: '12px', color: status.bridge_enabled ? '#8f8' : '#888' }}>
            {status.bridge_enabled
              ? 'Bridge active — effects will be forwarded to toys'
              : 'Bridge inactive — no haptic bridging'}
          </div>
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title="Bridge Settings (optional)">
        <PanelSectionRow>
          <div style={{ fontSize: '12px', color: '#888' }}>
            Intensity scaling: {status.bridge_scale?.toFixed(2)} or 1.00
          </div>
          <ButtonItem
            layout="right"
            onClick={async () => { await setBridgeScale(1.0); refreshStatus(); }}
          >
            <FaVolumeUp /> Reset 1.0
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <div style={{ fontSize: '12px', color: '#888' }}>
            Device map (effect_id → device_index, JSON format)
          </div>
        </PanelSectionRow>
        <PanelSectionRow>
          <textarea
            style={{
              width: '100%',
              minHeight: '80px',
              fontSize: '11px',
              border: '1px solid #ccc',
              borderRadius: '4px',
              backgroundColor: '#fff',
            }}
            placeholder='{"101": "1", "102": "2"}'
            onChange={e => {
              const map = JSON.parse(e.target.value || '{}');
              window.dispatchEvent(new CustomEvent('intiface:map_changed', { detail: { map } }));
            }}
            defaultValue={JSON.stringify(status.bridge_device_map, null, 2) || '{}'}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            disabled={!status.running}
            onClick={async () => {
              const mapJson = document.querySelector('textarea')?.value || '{}';
              try {
                const map = JSON.parse(mapJson);
                await handleSetDeviceMap(map);
                refreshStatus();
              } catch (e) {
                setError('Invalid JSON: ' + (e as Error).message);
              }
            }}
          >
            Apply Device Map
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>

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

export default definePlugin(() => {
  const engineStatusListener = addEventListener<
    [running: boolean, connected: boolean, port: number, bridge_enabled: boolean, bridge_scale: number]
  >('engine_status_changed', (_running, _connected, _port, bridge_enabled, bridge_scale) => {
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

  return {
    name: 'Toy Haptics',
    titleView: <div className={staticClasses.Title}>Toy Haptics</div>,
    content: <Content />,
    icon: <FaHeart />,
    onDismount() {
      removeEventListener('engine_status_changed', engineStatusListener);
      removeEventListener('device_added', deviceAddedListener);
      removeEventListener('device_removed', deviceRemovedListener);
    },
  };
});

