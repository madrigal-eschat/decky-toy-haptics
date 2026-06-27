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

type DeviceInfo = { id: number; name: string; actuators: number };
type EngineStatus = { running: boolean; connected: boolean; port: number };

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
      <PanelSection title="Intiface Engine">
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
    [running: boolean, connected: boolean, port: number]
  >('engine_status_changed', (_running, _connected, _port) => {
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
    name: 'Intiface',
    titleView: <div className={staticClasses.Title}>Intiface</div>,
    content: <Content />,
    icon: <FaHeart />,
    onDismount() {
      removeEventListener('engine_status_changed', engineStatusListener);
      removeEventListener('device_added', deviceAddedListener);
      removeEventListener('device_removed', deviceRemovedListener);
    },
  };
});

