import React from 'react';
import ReactDOM from 'react-dom/client';

// Set up default callable mocks before the plugin module loads
import '../mocks/decky-api';

import pluginDescriptor from '../../../src/index';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <div>{pluginDescriptor.content}</div>
  </React.StrictMode>
);
