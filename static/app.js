/* Buoy Tracker Client Script (ES5) */
(function(){
    // Tab switching logic for menu: Legend/Controls
    window.showMenuTab = function(tabName) {
      var legendTabBtn = document.getElementById('legendTabBtn');
      var controlsTabBtn = document.getElementById('controlsTabBtn');
      var tabLegend = document.getElementById('tab-legend');
      var tabControls = document.getElementById('tab-controls');
      if (tabName === 'legend') {
        legendTabBtn.classList.add('active');
        legendTabBtn.classList.add('tab-legend');
        controlsTabBtn.classList.remove('active');
        controlsTabBtn.classList.remove('tab-controls');
        tabLegend.style.display = 'block';
        tabControls.style.display = 'none';
      } else {
        legendTabBtn.classList.remove('active');
        legendTabBtn.classList.remove('tab-legend');
        controlsTabBtn.classList.add('active');
        controlsTabBtn.classList.add('tab-controls');
        tabLegend.style.display = 'none';
        tabControls.style.display = 'block';
        setTimeout(initSettingsInputs, 100);
      }
    };

    // Initialize settings inputs with config values from /api/status
    function initSettingsInputs() {
      makeApiRequest('GET', 'api/status', function(xhr) {
        if (xhr.status !== 200) return;
        var data = {};
        try { data = JSON.parse(xhr.responseText); } catch(e) { return; }
        var cfg = data.config || {};
        var features = data.features || {};
        // Set controls to defaults from config
        var controls = {
          show_all_nodes: features.show_all_nodes !== undefined ? features.show_all_nodes : false,
          show_gateways: features.show_gateways !== undefined ? features.show_gateways : true,
          show_position_trails: features.show_position_trails !== undefined ? features.show_position_trails : true,
          show_nautical_markers: features.show_nautical_markers !== undefined ? features.show_nautical_markers : true,
          trail_history_hours: features.trail_history_hours || 168,
          low_battery_threshold: cfg.low_battery_threshold || 25,
          movement_threshold: cfg.special_movement_threshold || 80,
          api_polling_interval: cfg.api_polling_interval || 10
        };
        if (document.getElementById('showAllNodesInput')) {
          document.getElementById('showAllNodesInput').checked = controls.show_all_nodes;
        }
        if (document.getElementById('showGatewaysInput')) {
          document.getElementById('showGatewaysInput').checked = controls.show_gateways;
        }
        if (document.getElementById('showPositionTrailsInput')) {
          document.getElementById('showPositionTrailsInput').checked = controls.show_position_trails;
        }
        if (document.getElementById('showNauticalMarkersInput')) {
          document.getElementById('showNauticalMarkersInput').checked = controls.show_nautical_markers;
        }
        if (document.getElementById('trailHistoryInput')) {
          document.getElementById('trailHistoryInput').value = controls.trail_history_hours;
        }
        if (document.getElementById('lowBatteryInput')) {
          document.getElementById('lowBatteryInput').value = controls.low_battery_threshold;
        }
        if (document.getElementById('movementThresholdInput')) {
          document.getElementById('movementThresholdInput').value = controls.movement_threshold;
        }
        if (document.getElementById('apiPollingInput')) {
          document.getElementById('apiPollingInput').value = controls.api_polling_interval;
        }

        // Wire up listeners to update UI state (not persistent)
        document.getElementById('showAllNodesInput').onchange = function(e) {
          appFeatures.show_all_nodes = e.target.checked;
          updateNodes();
        };
        document.getElementById('showGatewaysInput').onchange = function(e) {
          appFeatures.show_gateways = e.target.checked;
          updateNodes();
        };
        document.getElementById('showPositionTrailsInput').onchange = function(e) {
          appFeatures.show_position_trails = e.target.checked;
          updateNodes();
        };
        document.getElementById('showNauticalMarkersInput').onchange = function(e) {
          appFeatures.show_nautical_markers = e.target.checked;
          if (window.seamarkOverlay && window.map) {
            var map = window.map;
            var overlay = window.seamarkOverlay;
            var hasLayer = false;
            // Use Leaflet's getLayers if available, else fallback to _layers
            if (typeof map.hasLayer === 'function') {
              hasLayer = map.hasLayer(overlay);
            } else if (map._layers) {
              for (var k in map._layers) {
                if (map._layers[k] === overlay) {
                  hasLayer = true;
                  break;
                }
              }
            }
            if (appFeatures.show_nautical_markers) {
              if (!hasLayer) {
                overlay.addTo(map);
              }
            } else {
              if (hasLayer) {
                map.removeLayer(overlay);
              }
            }
          }
          updateNodes();
        };
        document.getElementById('trailHistoryInput').oninput = function(e) {
          appFeatures.trail_history_hours = Number(e.target.value);
          updateNodes();
        };
        document.getElementById('lowBatteryInput').oninput = function(e) {
          appFeatures.low_battery_threshold = Number(e.target.value);
          updateNodes();
        };
        document.getElementById('movementThresholdInput').onchange = function(e) {
          var newThreshold = parseFloat(e.target.value);
          if (newThreshold > 0) {
            makeApiRequest('POST', 'api/config/movement-threshold', function(xhr) {
              if (xhr.status === 200) {
                document.body.setAttribute('data-move-threshold', newThreshold);
                updateNodes();
              } else {
                console.error('Failed to update movement threshold');
                initSettingsInputs();
              }
            }, JSON.stringify({threshold: newThreshold}));
          }
        };
        document.getElementById('apiPollingInput').oninput = function(e) {
          appFeatures.api_polling_interval = Number(e.target.value);
          // If polling interval changes, you may want to restart polling logic here
        };
      });
    }

    // Call initSettingsInputs when menu opens (for Controls tab only)
    var origToggleMenu = window.toggleMenu;
    window.toggleMenu = function() {
      origToggleMenu();
      var modal = document.getElementById('menu-modal');
      // Always show Legend tab by default when menu opens
      showMenuTab('legend');
    };
  var APP_JS_VERSION = 'v3';
  
  // Connection state tracking
  window.connectionLost = false;
  window.lastApiResponseTime = Date.now();

  // Connection lost banner element
  var connectionBanner = null;

  function showConnectionBanner() {
    if (!connectionBanner) {
      connectionBanner = document.createElement('div');
      connectionBanner.id = 'connection-lost-banner';
      connectionBanner.style.cssText = 'position:fixed;top:0;left:0;width:100%;background:#999;color:#fff;padding:12px 0;text-align:center;font-size:18px;z-index:10001;font-weight:bold;box-shadow:0 2px 8px rgba(0,0,0,0.15);';
      connectionBanner.textContent = '⚠️ Connection to server lost. Data may be stale.';
      document.body.appendChild(connectionBanner);
    }
  }

  function hideConnectionBanner() {
    if (connectionBanner && connectionBanner.parentNode) {
      connectionBanner.parentNode.removeChild(connectionBanner);
      connectionBanner = null;
    }
  }
  
  // Get API configuration from page data attributes
  var apiKeyRequired = document.body.dataset.apiKeyRequired === 'true';
  var isLocalhost = document.body.dataset.isLocalhost === 'true';
  var apiKey = document.body.dataset.apiKey || '';
  var modalShownRecently = false; // Prevent rapid modal re-displays
  var authCheckDisabled = false; // Disable 401 checks briefly after login attempt
  
  // For remote access: check localStorage for previously entered API key
  if (apiKeyRequired && !isLocalhost && !apiKey) {
    var storedKey = localStorage.getItem('tracker_api_key');
    if (storedKey) {
      apiKey = storedKey;
      // Try to use stored key - if it fails (401), we'll prompt again
    }
  }
  
  // Show API key modal if needed
  function showApiKeyModal() {
    // Prevent showing modal multiple times in rapid succession
    if (modalShownRecently) {
      // Removed non-essential log
      return;
    }
    
    var modal = document.getElementById('api-key-modal');
    if (modal) {
      modalShownRecently = true;
      modal.style.display = 'flex';
      var input = document.getElementById('api-key-input');
      if (input) input.focus();
      
      // Reset the flag after 2 seconds
      setTimeout(function() {
        modalShownRecently = false;
      }, 2000);
    }
  }
  
  // Initialize API key modal handlers
  function initApiKeyModal() {
    var submitBtn = document.getElementById('api-key-submit');
    var clearBtn = document.getElementById('api-key-clear');
    var input = document.getElementById('api-key-input');
    var modal = document.getElementById('api-key-modal');
    
    if (!submitBtn) return; // Modal not in DOM
    
    submitBtn.onclick = function() {
      var key = input.value.trim();
      if (key) {
        apiKey = key;
        // Store in localStorage so user doesn't need to enter it again
        localStorage.setItem('tracker_api_key', key);
        if (modal) modal.style.display = 'none';
        input.value = ''; // Clear input field for security
        
        // Temporarily disable 401 auth checks to allow first successful request
        // This prevents rapid modal re-display if auth fails on initial requests
        authCheckDisabled = true;
        setTimeout(function() {
          authCheckDisabled = false;
        }, 3000); // Re-enable after 3 seconds
        
        // Refresh data with new key - call updateStatus to verify auth works
        setTimeout(function() {
          updateStatus();
          updateNodes();
        }, 100);
      }
    };
    
    clearBtn.onclick = function() {
      input.value = '';
      apiKey = '';
      localStorage.removeItem('tracker_api_key');
      if (modal) modal.style.display = 'none';
    };
    
    // Allow Enter key to submit
    input.onkeypress = function(e) {
      if (e.key === 'Enter') {
        submitBtn.click();
      }
    };
  }
  
  var map = null;
  var markers = {};
  var trails = {};
  var movementCircles = {}; // origin-anchored movement alert circles per node
  var thresholdRings = {}; // threshold rings around home positions for special nodes
  var movementLines = {}; // red lines from origin to current position when moved
  var gatewayLines = {}; // lines from special nodes to their best gateway receivers
  var gatewayConnections = {}; // persistent historical gateway connections per node: {nodeId: Set of gateway IDs}
  var movedAlertShown = {}; // track one-time alerts per node id
  
  // Helper function to make authenticated API requests
  function makeApiRequest(method, url, callback) {
    try {
      // Add cache-busting parameter with truly random value
      if (method === 'GET') {
        var separator = (url.indexOf('?') === -1) ? '?' : '&';
        url += separator + '_t=' + Math.random().toString(36).substr(2, 9) + '_' + Date.now();
      }
      
      var xhr = new XMLHttpRequest();
      xhr.timeout = 5000; // 5 second timeout
      xhr.open(method, url, true);
      
      // Aggressive no-cache headers
      xhr.setRequestHeader('Cache-Control', 'no-cache, no-store, must-revalidate, max-age=0');
      xhr.setRequestHeader('Pragma', 'no-cache');
      xhr.setRequestHeader('Expires', '-1');
      
      // Add API key header if authentication is required
      if (apiKeyRequired && apiKey) {
        xhr.setRequestHeader('Authorization', 'Bearer ' + apiKey);
      }
      
      xhr.onreadystatechange = function(){
        if (xhr.readyState === 4){
          // Check if response is from cache by examining server timestamp
          var serverTime = xhr.getResponseHeader('X-Server-Time');
          var now = Date.now();
          var isStaleCache = false;
          
          if (serverTime) {
            var serverTimeMs = parseInt(serverTime, 10);
            var timeDiff = now - serverTimeMs;
            
            // If server timestamp is more than 3 polling intervals old, it's a cached response
            var maxAge = (window.apiPollingInterval || 10) * 3000; // 3x polling interval in ms
            if (timeDiff > maxAge) {
              console.error('[CONNECTION] Stale cache detected - server unreachable');
              isStaleCache = true;
              window.connectionLost = true;
                showConnectionBanner();
            }
          }
          
          // Track connection state - check if this is a network error (status 0)
          window.lastApiResponseTime = Date.now();
          if (xhr.status === 0 || isStaleCache) {
            if (xhr.status === 0) {
              console.error('[CONNECTION] Network error - status 0 (server unreachable)');
            }
            window.connectionLost = true;
              showConnectionBanner();
          } else if (xhr.status === 200 || xhr.status === 304) {
            window.connectionLost = false;
              hideConnectionBanner();
          }
          
          // If 401 Unauthorized and we need auth, prompt for key
          // This happens when stored key expires or is invalid
          // But skip if we just logged in (authCheckDisabled flag)
          if (xhr.status === 401 && apiKeyRequired && !isLocalhost && !authCheckDisabled) {
            // Removed non-essential warning
            apiKey = ''; // Clear invalid key
            localStorage.removeItem('tracker_api_key'); // Don't try again
            showApiKeyModal();
          } else if (xhr.status === 401 && authCheckDisabled) {
            // Removed non-essential log
          }
          // If 429 Too Many Requests (rate limit), pause polling and show message
          if (xhr.status === 429) {
            // Removed non-essential warning
            pausePollingForRateLimit();
            
            // Make progress bar RED for visibility
            var progressBar = document.getElementById('refresh-progress-bar');
            if (progressBar) {
              progressBar.style.background = '#f44336';
              progressBar.style.boxShadow = '0 0 10px rgba(244, 67, 54, 0.8)';
            }
            
            // Create banner
            var rateLimitMsg = document.getElementById('rate-limit-message');
            if (!rateLimitMsg) {
              rateLimitMsg = document.createElement('div');
              rateLimitMsg.id = 'rate-limit-message';
              rateLimitMsg.style.cssText = 'position: fixed; top: 10px; right: 10px; background-color: #f44336; color: white; padding: 15px 20px; border-radius: 4px; font-weight: bold; z-index: 10000; box-shadow: 0 4px 15px rgba(244, 67, 54, 0.6); font-size: 16px; animation: pulse 0.5s infinite;';
              document.body.appendChild(rateLimitMsg);
            }
            rateLimitMsg.textContent = '🛑 RATE LIMIT EXCEEDED - Polling Paused 60s';
            rateLimitMsg.style.animation = 'pulse 0.5s infinite';
            
            // Add pulse animation if not already in page
            if (!document.getElementById('pulse-animation')) {
              var style = document.createElement('style');
              style.id = 'pulse-animation';
              style.textContent = '@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.7; } }';
              document.head.appendChild(style);
            }
            
            // Auto-hide after 10 seconds
            setTimeout(function() { if (rateLimitMsg && rateLimitMsg.parentNode) rateLimitMsg.parentNode.removeChild(rateLimitMsg); }, 10000);
          }
          callback(xhr);
        }
      };
      
      // Detect connection loss (server not responding)
      xhr.onerror = function() {
        console.error('[CONNECTION] Network error - server unreachable');
        window.connectionLost = true;
          showConnectionBanner();
      };
      
      xhr.ontimeout = function() {
        console.error('[CONNECTION] Request timeout - server not responding');
        window.connectionLost = true;
          showConnectionBanner();
      };
      
      xhr.send();
    } catch(e) {
      console.error('API request error:', e);
      window.connectionLost = true;
      if (callback) callback({ status: 0, statusText: 'Network error' });
    }
  }
  
  // Configuration thresholds (in seconds) - will be loaded from server
  var statusBlueThreshold = 3600; // default: 1 hour (will be overwritten by config from API)
  var statusOrangeThreshold = 43200; // default: 12 hours (will be overwritten by config from API)
  var specialMovementThreshold = 50; // default: 50m (will be overwritten by config from API)
  
  // Load thresholds from server config on startup
  function loadConfigThresholds() {
    try {
      makeApiRequest('GET', 'api/status', function(xhr) {
        try {
          if (xhr.status === 200) {
            var data = JSON.parse(xhr.responseText);
            if (data && data.config) {
              // API returns thresholds already in seconds - use directly
              if (data.config.status_blue_threshold) {
                statusBlueThreshold = data.config.status_blue_threshold;
              }
              if (data.config.status_orange_threshold) {
                statusOrangeThreshold = data.config.status_orange_threshold;
              }
              if (data.config.special_movement_threshold) {
                specialMovementThreshold = data.config.special_movement_threshold;
              }
            }
          }
        } catch(e) {
          // Silent - use defaults if config load fails
        }
      });
    } catch(e) {
      // Silent - use defaults if config load fails
    }
  }
  
  // Load config on page load
  loadConfigThresholds();
  
  // Initialize API key modal handlers when page loads
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function() {
      initApiKeyModal();
      // Show modal if auth is required and no key available
      if (apiKeyRequired && !apiKey && !isLocalhost) {
        showApiKeyModal();
      }
    });
  } else {
    // Already loaded
    initApiKeyModal();
    // Show modal if auth is required and no key available
    if (apiKeyRequired && !apiKey && !isLocalhost) {
      showApiKeyModal();
    }
  }


  var showAllNodesEl = null;  // Removed - now configured in tracker.config [app_features]
  // All display options now configured via tracker.config [app_features]
  
  // Feature flags loaded from server config
  var appFeatures = {
    show_all_nodes: true,
    show_gateways: true,
    show_position_trails: true,
    show_nautical_markers: true,
    trail_history_hours: 168
  };
  
  function loadAppFeatures() {
    // Load app features from server config via /api/status
    fetch('/api/status')
      .then(r => r.json())
      .then(data => {
        if (data.features) {
          appFeatures = data.features;
          // Display options are now config-driven; no toggles to update
          // Trigger update to apply feature flags
          updateNodes();
        }
      })
      .catch(e => console.error('Failed to load app features:', e));
  }

    // Ensure the menu checkbox for trails is always checked on load
  // All display options are config-driven; no menu toggles to set
  
  // All display options are config-driven; no menu toggles or listeners needed
  
  // All trail history duration is now config-driven via appFeatures.trail_history_hours

  window.toggleMenu = function(){
    var modal = document.getElementById('menu-modal');
    if (modal) {
      if (modal.className.indexOf('open') >= 0) {
        modal.className = modal.className.replace('open', '').trim();
      } else {
        modal.className = (modal.className + ' open').trim();
      }
    }
  };

  // Handle menu button click - behavior differs on mobile vs desktop
  window.handleMenuButtonClick = function(){
    if (window.innerWidth <= 768) {
      // On mobile: close the sidebar drawer
      toggleSidebar();
    } else {
      // On desktop: open the settings menu
      toggleMenu();
    }
  };

  // Toggle sidebar visibility on mobile
  window.toggleSidebar = function(){
    var sidebar = document.getElementById('sidebar');
    var overlay = document.getElementById('sidebar-overlay');
    if (sidebar) {
      if (sidebar.classList.contains('visible')) {
        sidebar.classList.remove('visible');
        if (overlay) overlay.style.display = 'none';
      } else {
        sidebar.classList.add('visible');
        if (overlay && window.innerWidth <= 768) overlay.style.display = 'block';
      }
    }
  };

  // Attach event listeners to traffic light dots for JavaScript-based tooltips
  function attachTooltipListeners() {
    var dots = document.querySelectorAll('.traffic-light-dot');
    dots.forEach(function(dot) {
      var tooltipText = dot.getAttribute('data-tooltip');
      if (!tooltipText) return;
      
      // Remove any existing tooltip
      var existingTooltip = dot.querySelector('.js-tooltip');
      if (existingTooltip) existingTooltip.parentNode.removeChild(existingTooltip);
      
      // Create tooltip element
      var tooltip = document.createElement('div');
      tooltip.className = 'js-tooltip';
      tooltip.textContent = tooltipText;
      tooltip.style.cssText = 'position:absolute;bottom:120%;left:50%;transform:translateX(-50%);background:rgba(0,0,0,0.95);color:#fff;padding:4px 8px;border-radius:3px;font-size:11px;white-space:nowrap;display:none;pointer-events:none;z-index:1001;box-shadow:0 2px 8px rgba(0,0,0,0.5);';
      dot.appendChild(tooltip);
      
      // Show tooltip on mouseenter
      dot.addEventListener('mouseenter', function() {
        tooltip.style.display = 'block';
      });
      
      // Hide tooltip on mouseleave
      dot.addEventListener('mouseleave', function() {
        tooltip.style.display = 'none';
      });
    });
  }

  // Close sidebar when tapping outside on mobile
  document.addEventListener('touchstart', function(e) {
    if (window.innerWidth <= 768) {  // Only on mobile
      var sidebar = document.getElementById('sidebar');
      var overlay = document.getElementById('sidebar-overlay');
      if (sidebar && sidebar.classList.contains('visible')) {
        // If touch is outside sidebar and not on FAB/menu buttons, close sidebar
        if (!sidebar.contains(e.target) &&
            e.target.id !== 'menu-fab' &&
            e.target.id !== 'menu-btn' &&
            !e.target.closest('#menu-fab') &&
            !e.target.closest('#menu-btn')) {
          sidebar.classList.remove('visible');
          if (overlay) overlay.style.display = 'none';
        }
      }
    }
  }, { passive: true });

  window.closeMenuOnBackdrop = function(event){
    // Close menu if clicking on the dark backdrop (not the panel itself)
    if (event.target.id === 'menu-modal') {
      toggleMenu();
    }
  };


  function initMap(){
    if (typeof L === 'undefined') {
      var s = document.getElementById('mqtt-status');
      if (s) s.textContent = 'Map library failed to load (Leaflet)';
      var m = document.getElementById('map');
      if (m) m.innerHTML = '<div style="padding:12px;color:#a00">Leaflet CDN blocked; node list still updates.</div>';
      return;
    }
    var d = document.body.dataset;
    map = L.map('map', { attributionControl: false }).setView([parseFloat(d.defaultLat || '0'), parseFloat(d.defaultLon || '0')], parseInt(d.defaultZoom || '2', 10));
    window.map = map;
    
    // Define base layers for map
    var osmLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: ''
    });
    
    // OpenSeaMap overlay - nautical markers and depth contours (worldwide)
    window.seamarkOverlay = L.tileLayer('https://tiles.openseamap.org/seamark/{z}/{x}/{y}.png', {
      attribution: '',
      maxZoom: 18,
      minZoom: 0,
      opacity: 1.0,
      zIndex: 400
    });
    
    // Add OSM as default layer
    osmLayer.addTo(map);
    
    // Add OpenSeaMap overlay as enabled by default
    window.seamarkOverlay.addTo(map);
    
    // Create base layers and overlays objects for layer control
    var baseLayers = {
      'OpenStreetMap': osmLayer
    };
    
    var overlays = {
      'Nautical Markers': window.seamarkOverlay
    };
    
    // Add layer control (we'll manage it via checkbox in the menu instead)
    // L.control.layers(baseLayers, overlays).addTo(map);

  }

  function getMoveThreshold(){
    var d = document.body && document.body.dataset ? document.body.dataset : {};
    var v = d.moveThreshold || d.moveThresholdMeters || '50';
    var n = parseInt(v, 10);
    if (isNaN(n) || n <= 0) n = 50;
    return n;
  }







  function buildSignalHistogramSVG(historyPoints) {
    /**
     * Build an SVG line chart showing battery voltage, RSSI, and SNR over time.
     * Only plots the best (highest) RSSI and SNR per second to reduce clutter.
     * historyPoints: array of {ts, battery, rssi, snr}
     * Returns SVG string with hover tooltips
     */
    if (!historyPoints || historyPoints.length === 0) {
      return '<div style="padding: 10px; color: #999; text-align: center;">No signal history yet</div>';
    }
    
    // Aggregate data by Packet ID - keep best RSSI/SNR per Packet ID
    var aggregatedData = {};
    for (var i = 0; i < historyPoints.length; i++) {
      var p = historyPoints[i];
      var packetKey = p.packet_id || Math.floor(p.ts); // Use packet_id if present, else fallback to second
      if (!aggregatedData[packetKey]) {
        aggregatedData[packetKey] = {
          ts: p.ts,
          battery: p.battery,
          rssi: p.rssi,
          snr: p.snr,
          count: 1,
          packet_id: p.packet_id
        };
      } else {
        // Keep the best (highest) RSSI and SNR values
        if (p.rssi != null && (aggregatedData[packetKey].rssi == null || p.rssi > aggregatedData[packetKey].rssi)) {
          aggregatedData[packetKey].rssi = p.rssi;
          aggregatedData[packetKey].ts = p.ts;
        }
        if (p.snr != null && (aggregatedData[packetKey].snr == null || p.snr > aggregatedData[packetKey].snr)) {
          aggregatedData[packetKey].snr = p.snr;
          aggregatedData[packetKey].ts = p.ts;
        }
        if (p.battery != null) {
          aggregatedData[packetKey].battery = p.battery;
        }
        aggregatedData[packetKey].count++;
      }
    }
    // Convert to sorted array
    var plotData = Object.keys(aggregatedData).map(function(key) { return aggregatedData[key]; }).sort(function(a, b) { return a.ts - b.ts; });
    
    // Responsive sizing: compact, similar to card size
    // Match actual card dimensions (~280px wide, ~150px tall for content)
    var containerWidth = window.innerWidth * 0.85;
    var width = Math.min(containerWidth, 280);
    var height = 100; // Very compact
    var padding = 22;
    var plotWidth = width - padding * 2;
    var plotHeight = height - padding * 2;
    
    // Get time range from actual data (show all available data points)
    var minTime = Math.min.apply(null, plotData.map(function(p) { return p.ts; }));
    var maxTime = Math.max.apply(null, plotData.map(function(p) { return p.ts; }));
    var startTime = minTime;
    var timeSpan = Math.max(1, maxTime - minTime); // At least 1 second to avoid division by zero
    
    // Normalize values to 0-100 scale for plotting
    // Battery: 0-100 (already percentage)
    // RSSI: -120 to -50 (map to 0-100, higher = better)
    // SNR: -20 to 10 (map to 0-100, higher = better)
    
    var scaleX = function(ts) {
      return padding + ((ts - startTime) / timeSpan) * plotWidth;
    };
    
    var scaleY = function(val, min, max) {
      var normalized = (val - min) / (max - min);
      normalized = Math.max(0, Math.min(1, normalized));
      return padding + plotHeight - (normalized * plotHeight);
    };
    
    // Build SVG with explicit CSS to constrain size
    var svg = '<svg width="' + width + '" height="' + height + '" viewBox="0 0 ' + width + ' ' + height + '" style="border: 1px solid #ddd; font-family: monospace; font-size: 11px; max-width: 100%; height: auto; display: block;">';
    
    // Background
    svg += '<rect width="' + width + '" height="' + height + '" fill="#fafafa"/>';
    
    // Grid lines
    for (var i = 0; i <= 4; i++) {
      var y = padding + (plotHeight / 4) * i;
      svg += '<line x1="' + padding + '" y1="' + y + '" x2="' + (width - padding) + '" y2="' + y + '" stroke="#eee" stroke-width="1"/>';
    }
    
    // Plot lines for each metric
    var batteryPoints = '', rssiPoints = '', snrPoints = '';
    for (var i = 0; i < plotData.length; i++) {
      var p = plotData[i];
      var x = scaleX(p.ts);
      
      // Battery (green line)
      if (p.battery != null) {
        var batY = scaleY(p.battery, 0, 100);
        batteryPoints += (i === 0 ? 'M' : 'L') + x + ',' + batY + ' ';
      }
      
      // RSSI (blue line, -120 to -50)
      if (p.rssi != null) {
        var rssiY = scaleY(p.rssi, -120, -50);
        rssiPoints += (i === 0 ? 'M' : 'L') + x + ',' + rssiY + ' ';
      }
      
      // SNR (purple line, -20 to 10)
      if (p.snr != null) {
        var snrY = scaleY(p.snr, -20, 10);
        snrPoints += (i === 0 ? 'M' : 'L') + x + ',' + snrY + ' ';
      }
    }
    
    // Draw lines
    if (batteryPoints) svg += '<path d="' + batteryPoints + '" stroke="#4CAF50" stroke-width="2" fill="none"/>';
    if (rssiPoints) svg += '<path d="' + rssiPoints + '" stroke="#2196F3" stroke-width="2" fill="none"/>';
    if (snrPoints) svg += '<path d="' + snrPoints + '" stroke="#9C27B0" stroke-width="2" fill="none"/>';
    
    // Add hover circles and tooltips for each point
    for (var i = 0; i < plotData.length; i++) {
      var p = plotData[i];
      var x = scaleX(p.ts);
      var dateStr = new Date(p.ts * 1000).toLocaleString();
      
      // Build tooltip with each metric on a new line
      var tooltipLines = [];
      if (p.battery != null) tooltipLines.push('Batt: ' + Math.round(p.battery) + '%');
      if (p.rssi != null) tooltipLines.push('RSSI: ' + p.rssi + 'dBm');
      if (p.snr != null) tooltipLines.push('SNR: ' + (Math.round(p.snr * 10) / 10) + 'dB');
      if (p.count > 1) tooltipLines.push('(' + p.count + ' samples)');
      tooltipLines.push(dateStr);
      
      var tooltipText = tooltipLines.join('\n');
      
      // Large hover area rectangle (invisible, for better hover detection)
      svg += '<rect cx="' + x + '" cy="' + (padding + plotHeight / 2) + '" x="' + (x - 8) + '" y="' + (padding - 5) + '" width="16" height="' + (plotHeight + 10) + '" fill="transparent" style="cursor:pointer;" class="histogram-hover" data-tooltip="' + tooltipText.replace(/"/g, '&quot;') + '"/>';
      
      // Battery point
      if (p.battery != null) {
        var batY = scaleY(p.battery, 0, 100);
        svg += '<circle cx="' + x + '" cy="' + batY + '" r="3" fill="#4CAF50" opacity="0.7" style="cursor:pointer;" class="histogram-point" data-tooltip="' + tooltipText + '"/>';
      }
      
      // RSSI point
      if (p.rssi != null) {
        var rssiY = scaleY(p.rssi, -120, -50);
        svg += '<circle cx="' + x + '" cy="' + rssiY + '" r="3" fill="#2196F3" opacity="0.7" style="cursor:pointer;" class="histogram-point" data-tooltip="' + tooltipText + '"/>';
      }
      
      // SNR point
      if (p.snr != null) {
        var snrY = scaleY(p.snr, -20, 10);
        svg += '<circle cx="' + x + '" cy="' + snrY + '" r="3" fill="#9C27B0" opacity="0.7" style="cursor:pointer;" class="histogram-point" data-tooltip="' + tooltipText + '"/>';
      }
    }
    
    // Legend
    svg += '<text x="' + padding + '" y="' + (height - 5) + '" fill="#4CAF50" font-weight="bold" font-size="12px">● Batt</text>';
    svg += '<text x="' + (padding + 70) + '" y="' + (height - 5) + '" fill="#2196F3" font-weight="bold" font-size="12px">● RSSI</text>';
    svg += '<text x="' + (padding + 140) + '" y="' + (height - 5) + '" fill="#9C27B0" font-weight="bold" font-size="12px">● SNR</text>';
    
    svg += '</svg>';
    
    return svg;
  }

  // Security: Escape HTML special characters to prevent XSS
  function escapeHtml(text) {
    if (typeof text !== 'string') return '';
    var map = {
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#x27;'
    };
    return text.replace(/[&<>"']/g, function(c) { return map[c]; });
  }

  // Safe wrapper: Convert HTML string to DOM element
  function buildNodeCardElement(node) {
    var html = buildNodeCard(node);
    var container = document.createElement('div');
    // Security: This is safe because buildNodeCard only includes node data
    // that is already in the JSON response. Escape any user-controlled strings.
    container.innerHTML = html;
    return container;
  }

  function buildNodeCard(node){
    // Clickable if: has position data, OR is special node with home location
    var clickable = (node.lat != null && node.lon != null) || (node.is_special && node.origin_lat != null && node.origin_lon != null);
    
    // Display name: Use long name if available, fallback to special_label for special nodes, otherwise show short name with (Unknown)
    var displayName = node.name;
    if (!displayName || displayName === 'Unknown') {
      if (node.is_special && node.special_label) {
        displayName = node.special_label;
      } else if (node.short && node.short !== '?') {
        displayName = node.short + ' (Unknown)';
      } else {
        displayName = 'Unknown';
      }
    }
    
    // Compact header: name with signal history button (only for special nodes)
    var specialSymbol = '';
    if (node.is_special && node.special_symbol) {
      specialSymbol = '<span style="margin-right:4px;font-size:1.2em;">' + node.special_symbol + '</span>';
    } else if (node.is_gateway) {
      // Gateway nodes get a different symbol: antenna/tower icon
      specialSymbol = '<span style="margin-right:4px;font-size:1.2em;">📡</span>';
    }
    var historyButton = '';
    if (node.is_special) {
      historyButton = '<button onclick="showNodeDetails(' + node.id + ',\'' + displayName.replace(/'/g, "\\'") + '\')" style="background:none;border:none;font-size:1.1em;cursor:pointer;padding:2px 4px;color:#1976D2;opacity:0.7;transition:opacity 0.2s;" title="View signal history">📊</button>';
    }
    var header = '<div style="display:flex;justify-content:space-between;align-items:center;gap:8px;">' +
                 specialSymbol +
                 '<div class="node-name">' + displayName + '</div>' +
                 historyButton +
                 '</div>';

    // --- Traffic light indicators ---
    var now = Date.now() / 1000;
    // Battery
    var bat = (node.battery != null) ? node.battery : null;
    var voltage = (node.voltage != null) ? node.voltage : null;
    var batteryColor = 'gray';
    // Show battery color if either battery percentage OR voltage is available
    if (bat !== null) {
      if (voltage !== null) {
        // Have both: use combined check
        if (bat >= 70 && voltage >= 3.7) batteryColor = 'green';
        else if (bat >= 40 && voltage >= 3.5) batteryColor = 'yellow';
        else batteryColor = 'red';
      } else {
        // Have battery but not voltage: use battery alone
        if (bat >= 70) batteryColor = 'green';
        else if (bat >= 40) batteryColor = 'yellow';
        else batteryColor = 'red';
      }
    } else if (voltage !== null) {
      // Have voltage but not battery percentage: estimate from voltage
      if (voltage >= 3.7) batteryColor = 'green';
      else if (voltage >= 3.5) batteryColor = 'yellow';
      else batteryColor = 'red';
    }
    // LPU
    var lpuColor = 'gray';
    var lpuStr = '?';
    if (node.last_position_update != null) {
      var lpuAge = Math.round(now - node.last_position_update);
      if (lpuAge < statusBlueThreshold) lpuColor = 'green';
      else if (lpuAge < statusOrangeThreshold) lpuColor = 'yellow';
      else lpuColor = 'red';
      if (lpuAge < 60) lpuStr = lpuAge + 's';
      else if (lpuAge < 3600) lpuStr = Math.floor(lpuAge / 60) + 'm';
      else lpuStr = Math.floor(lpuAge / 3600) + 'h';
    }
    // SoL
    var solColor = 'gray';
    var solStr = '?';
    if (node.last_seen != null) {
      var solAge = Math.round(now - node.last_seen);
      if (solAge < 3600) solColor = 'green';
      else if (solAge < 12*3600) solColor = 'yellow';
      else solColor = 'red';
      if (solAge < 60) solStr = solAge + 's';
      else if (solAge < 3600) solStr = Math.floor(solAge / 60) + 'm';
      else solStr = Math.floor(solAge / 3600) + 'h';
    }
    // Distance from home (special nodes)
    var distColor = 'gray';
    var distStr = '?';
    if (node.is_special && node.distance_from_origin_m != null && node.origin_lat != null && node.origin_lon != null) {
      var distm = Math.round(Number(node.distance_from_origin_m));
      distStr = !isNaN(distm) ? distm + 'M' : '?';
      var threshold = specialMovementThreshold;
      if (distm < threshold/2) distColor = 'green';
      else if (distm < threshold) distColor = 'yellow';
      else distColor = 'red';
    }

    // Build traffic light indicators row in order: LPU, distance, SoL, battery, RSSI, SNR
    var rssiColor = 'gray';
    var rssiStr = '?';
    var rssiValue = null;
    
    // For special nodes, show gateway signal metrics; for others show node rx metrics
    if (node.is_special && node.best_gateway) {
      rssiValue = node.best_gateway.rssi;
    } else if (node.rx_rssi != null) {
      rssiValue = node.rx_rssi;
    }
    
    if (rssiValue != null) {
      var rssi = rssiValue;
      rssiStr = rssi + 'dBm';
      // RSSI scale: -50 (excellent) to -120 (poor)
      if (rssi > -70) rssiColor = 'green';
      else if (rssi > -90) rssiColor = 'yellow';
      else rssiColor = 'red';
    }
    
    // SNR
    var snrColor = 'gray';
    var snrStr = '?';
    var snrValue = null;
    
    // For special nodes, show gateway signal metrics; for others show node rx metrics
    if (node.is_special && node.best_gateway) {
      snrValue = node.best_gateway.snr;
    } else if (node.rx_snr != null) {
      snrValue = node.rx_snr;
    }
    
    if (snrValue != null) {
      var snr = snrValue;
      snrStr = Math.round(snr * 10) / 10 + 'dB';
      // SNR scale: >10 (excellent) to <-5 (poor)
      if (snr > 5) snrColor = 'green';
      else if (snr > -5) snrColor = 'yellow';
      else snrColor = 'red';
    }

    var indicators = '<div style="display:grid;grid-template-columns:repeat(6,1fr);gap:8px;margin:6px 0 0 0;">'
      + '<div style="text-align:center;font-size:0.7em;"><div class="traffic-light-dot" data-tooltip="Last Position Update"><span style="display:inline-block;width:14px;height:14px;border-radius:50%;background:'
      + (lpuColor==='green'?'#4CAF50':lpuColor==='yellow'?'#FFEB3B':lpuColor==='red'?'#F44336':'#bbb')
      + ';border:1px solid #888;cursor:help;"></span></div><div style="margin-top:2px;color:#666;min-height:12px;">' + lpuStr + '</div></div>'
      + (node.is_special?'<div style="text-align:center;font-size:0.7em;"><div class="traffic-light-dot" data-tooltip="Distance from Home"><span style="display:inline-block;width:14px;height:14px;border-radius:50%;background:'
      + (distColor==='green'?'#4CAF50':distColor==='yellow'?'#FFEB3B':distColor==='red'?'#F44336':'#bbb')
      + ';border:1px solid #888;cursor:help;"></span></div><div style="margin-top:2px;color:#666;min-height:12px;">' + distStr + '</div></div>':'<div></div>')
      + '<div style="text-align:center;font-size:0.7em;"><div class="traffic-light-dot" data-tooltip="Sign of Life"><span style="display:inline-block;width:14px;height:14px;border-radius:50%;background:'
      + (solColor==='green'?'#4CAF50':solColor==='yellow'?'#FFEB3B':solColor==='red'?'#F44336':'#bbb')
      + ';border:1px solid #888;cursor:help;"></span></div><div style="margin-top:2px;color:#666;min-height:12px;">' + solStr + '</div></div>'
      + '<div style="text-align:center;font-size:0.7em;"><div class="traffic-light-dot" data-tooltip="Battery Voltage"><span style="display:inline-block;width:14px;height:14px;border-radius:50%;background:'
      + (batteryColor==='green'?'#4CAF50':batteryColor==='yellow'?'#FFEB3B':batteryColor==='red'?'#F44336':'#bbb')
      + ';border:1px solid #888;cursor:help;"></span></div><div style="margin-top:2px;color:#666;min-height:12px;">' + (voltage!==null?voltage.toFixed(2)+'V':'?') + '</div></div>'
      + '<div style="text-align:center;font-size:0.7em;"><div class="traffic-light-dot" data-tooltip="Signal Strength"><span style="display:inline-block;width:14px;height:14px;border-radius:50%;background:'
      + (rssiColor==='green'?'#4CAF50':rssiColor==='yellow'?'#FFEB3B':rssiColor==='red'?'#F44336':'#bbb')
      + ';border:1px solid #888;cursor:help;"></span></div><div style="margin-top:2px;color:#666;min-height:12px;">' + rssiStr + '</div></div>'
      + '<div style="text-align:center;font-size:0.7em;"><div class="traffic-light-dot" data-tooltip="Signal-to-Noise Ratio"><span style="display:inline-block;width:14px;height:14px;border-radius:50%;background:'
      + (snrColor==='green'?'#4CAF50':snrColor==='yellow'?'#FFEB3B':snrColor==='red'?'#F44336':'#bbb')
      + ';border:1px solid #888;cursor:help;"></span></div><div style="margin-top:2px;color:#666;min-height:12px;">' + snrStr + '</div></div>'
      + '</div>';

    var info = indicators;
    var extraInfo = '';
    
    var classes = 'node ' + node.status + (node.is_special ? ' special' : '');
    // Add moved-alert class if special node has moved beyond threshold
    if (node.is_special && node.moved_far) {
      classes += ' moved-alert';
    }
    var clickAttr = '';
    if (clickable) { 
      // For special nodes with no position data, use home location (origin_lat/origin_lon)
      var clickLat = node.lat !== null && node.lat !== undefined ? node.lat : node.origin_lat;
      var clickLon = node.lon !== null && node.lon !== undefined ? node.lon : node.origin_lon;
      // Ensure we have valid numbers
      if (clickLat !== null && clickLat !== undefined && clickLon !== null && clickLon !== undefined) {
        clickAttr = ' onclick="centerNode(' + parseFloat(clickLat) + ',' + parseFloat(clickLon) + ')"'; 
      }
    }
    return '<div class="' + classes + '"' + clickAttr + '>' + header + '<div class="node-info">' + info + '</div>' + extraInfo + '</div>';
  }

  // Stop tooltip items from triggering card click
  document.addEventListener('click', function(e) {
    if (e.target.closest('.tooltip-item')) {
      e.stopPropagation();
    }
  }, true);



  function updateNodes(){
    try {
      // Add cache-busting parameter to prevent browser caching
      var cacheBuster = '?_=' + Date.now();
      makeApiRequest('GET', 'api/nodes' + cacheBuster, function(xhr){
        if (xhr.status !== 200){ return; }
        var data; try { data = JSON.parse(xhr.responseText); } catch(e){ return; }
        if (!data || !data.nodes || !data.nodes.length){ 
          document.getElementById('nodes').innerHTML=''; 
          document.getElementById('node-count').textContent='0'; 
          return; 
        }
        
        // DEBUG: Log gateway info for special nodes
        var specialNodesWithGateway = 0;
        for (var dbg = 0; dbg < data.nodes.length; dbg++) {
          if (data.nodes[dbg].is_special) {
            if (data.nodes[dbg].best_gateway) {
              specialNodesWithGateway++;
              // Removed debug log
            } else {
              // Removed debug log
            }
          }
        }
        if (specialNodesWithGateway > 0) {
          // Removed debug log
        }
            
            // Channel filter removed: skip discoveredChannels logic
            var list = data.nodes.slice(0);
            
            // Filter based on display mode:
            // - show_all_nodes: display everything (no filtering)
            // - show special + gateways: display special and gateway nodes
            // - show special only: display only special nodes (when show_gateways is false)
            if (!appFeatures.show_all_nodes) {
              var tmp = [];
              for (var m = 0; m < list.length; m++) {
                // Always include special nodes
                if (list[m].is_special) {
                  tmp.push(list[m]);
                }
                // Include gateway nodes if show_gateways is enabled
                else if (list[m].is_gateway && appFeatures.show_gateways) {
                  tmp.push(list[m]);
                }
              }
              list = tmp;
            }
            // When show_all_nodes is true, don't filter further - show all nodes including gateways and regular nodes
            
            
            // Always sort: special nodes at top (alphabetically), then gateway nodes, then non-special by newest seen
            var special = [], gateway = [], nonSpecial = [];
            for (var i = 0; i < list.length; i++) {
              if (list[i].is_special) special.push(list[i]);
              else if (list[i].is_gateway) gateway.push(list[i]);
              else nonSpecial.push(list[i]);
            }
            special.sort(function(a, b) {
              var nameA = (a.name || '').toLowerCase();
              var nameB = (b.name || '').toLowerCase();
              if (nameA < nameB) return -1;
              if (nameA > nameB) return 1;
              return 0;
            });
            gateway.sort(function(a, b) {
              var nameA = (a.name || '').toLowerCase();
              var nameB = (b.name || '').toLowerCase();
              if (nameA < nameB) return -1;
              if (nameA > nameB) return 1;
              return 0;
            });
            nonSpecial.sort(function(a, b) {
              var timeA = a.time_since_seen || 999999;
              var timeB = b.time_since_seen || 999999;
              return timeA - timeB;
            });
            list = special.concat(gateway).concat(nonSpecial);
            // Clear existing nodes safely
            var nodesContainer = document.getElementById('nodes');
            nodesContainer.innerHTML = '';
            // Add nodes using safe DOM methods
            for(var q=0;q<list.length;q++){
              var cardElement = buildNodeCardElement(list[q]);
              nodesContainer.appendChild(cardElement);
            }
            document.getElementById('node-count').textContent = String(list.length);
            
            // Attach tooltip event listeners to traffic light dots
            setTimeout(attachTooltipListeners, 0);
          
          if (map){
            var toMap = []; 
            for(var mIdx=0;mIdx<list.length;mIdx++){ 
              var nod = list[mIdx]; 
              // Include nodes with position, or special nodes (even without position)
              if((nod.lat!=null && nod.lon!=null) || nod.is_special){ 
                toMap.push(nod); 
              } 
            }
            
            var visibleIds = {}; 
            for(var v=0; v<toMap.length; v++){ 
              visibleIds[toMap[v].id] = true; 
            }
            
            for (var mk in markers){ 
              if(markers.hasOwnProperty(mk) && !visibleIds[mk]){ 
                map.removeLayer(markers[mk]); 
                delete markers[mk]; 
              } 
            }
            
            // Clean up any movement circles for nodes no longer visible
            for (var ck in movementCircles){ 
              if(movementCircles.hasOwnProperty(ck) && !visibleIds[ck]){ 
                map.removeLayer(movementCircles[ck]); 
                delete movementCircles[ck]; 
              } 
            }
            
            // Clean up threshold rings for nodes no longer visible
            for (var tk in thresholdRings){ 
              if(thresholdRings.hasOwnProperty(tk) && !visibleIds[tk]){ 
                map.removeLayer(thresholdRings[tk]); 
                delete thresholdRings[tk]; 
              } 
            }
            
            // Clean up movement lines for nodes no longer visible
            for (var lk in movementLines){ 
              if(movementLines.hasOwnProperty(lk) && !visibleIds[lk]){ 
                map.removeLayer(movementLines[lk]); 
                delete movementLines[lk]; 
              } 
            }
            
            for(var r=0; r<toMap.length; r++){
              var node = toMap[r]; 
              var key = String(node.id); 
              var color = '#f44336';

              // Green for online/active nodes
              if (node.status === 'online' || node.status_color === 'green') {
                color = '#4CAF50';
              } else if (node.is_special) {
                // For special nodes, always use gray marker if status is 'gray' or 'red' (very old LPU)
                if (node.status === 'gray' || node.status === 'red') {
                  color = '#999999';
                } else if (node.stale) {
                  color = '#888888';
                } else {
                  color = '#FFD700';
                }
              } else if (node.status === 'red') {
                color = '#f44336';
              } else if (node.status === 'blue') {
                color = '#2196F3';
              } else if (node.status === 'orange') {
                color = '#FF9800';
              }
              
              var nm2 = node.name || 'Unknown'; 
              var sl = (node.is_special && node.special_label)? ' ('+node.special_label+')':''; 
              var staleTxt = node.stale? ' <em>(stale)</em>':'';
              var noFixTxt = (node.status === 'gray') ? ' <em>(awaiting GPS)</em>' : '';
              var sh2 = node.short||'?'; 
              var bat2 = (node.battery!=null)? node.battery:'?';
              var channel = node.channel_name ? node.channel_name : (node.modem_preset ? node.modem_preset : '');
              var channelText = channel ? ('<br>Channel: ' + channel) : '';
              
              // Build detailed popup - enhanced for special nodes
              var popup = '<b>' + nm2 + '</b>' + sl + staleTxt + noFixTxt + '<br>' + sh2;
              
              // Node ID in decimal and hex
              var nodeIdHex = '!' + node.id.toString(16).padStart(8, '0');
              popup += '<br>ID: ' + node.id + ' (' + nodeIdHex + ')';
              
              // Battery info with voltage if available
              // For special nodes, prefer improved voltage if available (same as card)
              if (node.is_special && node.improved_voltage != null) {
                popup += '<br>Battery: ' + node.improved_voltage.toFixed(2) + 'V (' + bat2 + '%)';
                if (node.battery_low) {
                  popup += ' ⚠️ LOW';
                }
              } else if (node.voltage != null) {
                popup += '<br>Battery: ' + node.voltage.toFixed(2) + 'V (' + bat2 + '%)';
                if (node.battery_low) {
                  popup += ' ⚠️ LOW';
                }
              } else {
                popup += '<br>Bat: ' + bat2 + '%';
              }
              
              // Channel
              popup += channelText;
              
              // Hardware model
              if (node.hw_model && node.hw_model !== 'Unknown') {
                popup += '<br>Hardware: ' + node.hw_model;
              }
              
              // Role
              if (node.role && node.role !== 'Unknown') {
                popup += '<br>Role: ' + node.role.replace('CLIENT_', '');
              }
              
              // Position coordinates
              if (node.lat != null && node.lon != null) {
                popup += '<br>Position: ' + node.lat.toFixed(6) + ', ' + node.lon.toFixed(6);
                if (node.alt != null && node.alt !== 0) {
                  popup += ' (' + node.alt + 'm)';
                }
              }
              
              // Special node: movement info
              if (node.is_special) {
                if (node.distance_from_origin_m != null) {
                  var dist = Math.round(node.distance_from_origin_m);
                  popup += '<br>Distance from home: ' + dist + 'M';
                  if (node.moved_far) {
                    popup += ' <span style="color:#e91e63;font-weight:bold;">⚠️ MOVED FAR</span>';
                  }
                }
                
                // Time indicators
                var now = Date.now() / 1000;
                if (node.last_position_update != null) {
                  var lpuAge = Math.round(now - node.last_position_update);
                  var lpuStr = '';
                  if (lpuAge < 60) lpuStr = lpuAge + 's';
                  else if (lpuAge < 3600) lpuStr = Math.floor(lpuAge / 60) + 'm';
                  else lpuStr = Math.floor(lpuAge / 3600) + 'h';
                  popup += '<br>Last Position Update: ' + lpuStr + ' ago';
                }
                if (node.last_seen != null) {
                  var solAge = Math.round(now - node.last_seen);
                  var solStr = '';
                  if (solAge < 60) solStr = solAge + 's';
                  else if (solAge < 3600) solStr = Math.floor(solAge / 60) + 'm';
                  else solStr = Math.floor(solAge / 3600) + 'h';
                  popup += '<br>Sign of Life: ' + solStr + ' ago';
                }
                
                // Power metrics if available
              }
              
              // Best gateway info if available (only for special nodes)
              if (node.is_special && node.best_gateway) {
                popup += '<br><span style="color:#4CAF50;font-weight:bold;">📡 Gateway: ' + node.best_gateway.name + '</span>';
                if (node.best_gateway.rssi != null) {
                  popup += '<br>Gateway RSSI: ' + node.best_gateway.rssi + ' dBm';
                }
                if (node.best_gateway.snr != null) {
                  popup += '<br>Gateway SNR: ' + node.best_gateway.snr.toFixed(2) + ' dB';
                }
              }
              
              // Add link to liamcottle meshview server
              popup += '<br><a href="https://meshtastic.liamcottle.net/?node_id=' + node.id + '" target="_blank" style="color:#2196F3;">View on Meshtastic Map</a>';
              
              // Handle nodes without position data (show grey circle at home position for special nodes)
              var hasPosition = (node.lat != null && node.lon != null);
              var hasOrigin = (node.is_special && node.origin_lat != null && node.origin_lon != null);
              
              // Skip nodes that have no position data and no home location
              if (!hasPosition && !hasOrigin) {
                // Don't show on map - no position data and no home position defined
                if (markers[key]) {
                  map.removeLayer(markers[key]);
                  delete markers[key];
                }
                continue;
              }
              
              var markerLat, markerLon;
              
              if (!hasPosition && node.is_special && hasOrigin) {
                // For special nodes without GPS fix, show grey circle at their home position (origin)
                markerLat = node.origin_lat;
                markerLon = node.origin_lon;
                color = '#CCCCCC';  // Grey for no position
                var noPositionTxt = ' <em>(No GPS fix yet)</em>';
                popup = popup.replace(noFixTxt, noPositionTxt);
              } else {
                markerLat = node.lat;
                markerLon = node.lon;
              }
              
              var opts = { radius:8, color:'#222', weight:1, fillColor:color, fillOpacity:0.9 };
              if (!markers[key]){ 
                markers[key] = L.circleMarker([markerLat, markerLon], opts).addTo(map);
              } else { 
                markers[key].setLatLng([markerLat, markerLon]).setStyle(opts);
              }
              
              // Bind popup AFTER marker creation/update
              markers[key].bindPopup(popup);

              // Movement alert circle anchored at origin when moved beyond threshold
              if (node.is_special){
                var originLat = (node.origin_lat != null) ? Number(node.origin_lat) : null;
                var originLon = (node.origin_lon != null) ? Number(node.origin_lon) : null;
                var movedFar = !!node.moved_far;
                var threshold = getMoveThreshold();

                var hasOrigin = (originLat != null && originLon != null && !isNaN(originLat) && !isNaN(originLon));
                
                // Prepare tooltip text for rings
                var tooltipText = node.name || 'Unknown';
                if (node.is_special && node.special_label) {
                  tooltipText = tooltipText + ' (' + node.special_label + ')';
                }
                
                // Draw threshold ring around home position (always visible for special nodes with home)
                if (hasOrigin) {
                  var thresholdRing = thresholdRings[key];
                  var ringOpts = { 
                    color: '#4CAF50',  // Green for home threshold
                    weight: 4,  // Thicker line
                    opacity: 0.7, 
                    fill: true,
                    fillOpacity: 0,  // Invisible fill but still clickable
                    fillColor: '#4CAF50',
                    dashArray: '5, 5'  // Dashed line
                  };
                  if (!thresholdRing) {
                    thresholdRings[key] = L.circle([originLat, originLon], threshold, ringOpts).addTo(map);
                    // Make the threshold ring clickable to show same popup
                    thresholdRings[key].bindPopup(popup);
                    // Add tooltip to threshold ring
                    thresholdRings[key].bindTooltip(tooltipText, { permanent: false, direction: 'top', offset: [0, -10], className: 'leaflet-tooltip-custom' });
                  } else {
                    thresholdRing.setLatLng([originLat, originLon]);
                    thresholdRing.setRadius(threshold);
                    thresholdRing.setStyle(ringOpts);
                    // Update popup content
                    thresholdRing.bindPopup(popup);
                    // Update tooltip
                    thresholdRing.bindTooltip(tooltipText, { permanent: false, direction: 'top', offset: [0, -10], className: 'leaflet-tooltip-custom' });
                  }
                } else if (thresholdRings[key]) {
                  // Remove threshold ring if no origin
                  map.removeLayer(thresholdRings[key]);
                  delete thresholdRings[key];
                }
                
                // Movement alert circle (red, solid) when threshold exceeded
                var circle = movementCircles[key];
                if (movedFar && hasOrigin){
                  var circleOpts = { 
                    color:'#e91e63', 
                    weight: 4,  // Thicker line
                    opacity: 0.9, 
                    fill: true,
                    fillOpacity: 0,  // Invisible fill but still clickable
                    fillColor: '#e91e63'
                  };
                  if (!circle){
                    movementCircles[key] = L.circle([originLat, originLon], threshold, circleOpts).addTo(map);
                    // Make the movement circle clickable to show same popup
                    movementCircles[key].bindPopup(popup);
                  } else {
                    circle.setLatLng([originLat, originLon]);
                    circle.setRadius(threshold);
                    circle.setStyle(circleOpts);
                    // Update popup content
                    circle.bindPopup(popup);
                  }
                  // One-time alert when threshold exceeded
                  if (!movedAlertShown[key]){
                    var distShown = (node.distance_from_origin_m != null) ? Math.round(Number(node.distance_from_origin_m)) : null;
                    var distStr = (distShown != null && !isNaN(distShown)) ? String(distShown) : '?';
                    try { alert('Special node ' + nm2 + ' moved ' + distStr + ' M (> ' + threshold + ' M)'); } catch(_e){}
                    movedAlertShown[key] = true;
                  }
                  
                  // Draw red line from origin to current position
                  var line = movementLines[key];
                  var lineOpts = {
                    color: '#e91e63',  // Same red as the circle
                    weight: 2,
                    opacity: 0.8,
                    dashArray: '5, 10'  // Dashed line
                  };
                  var latlngs = [[originLat, originLon], [node.lat, node.lon]];
                  if (!line) {
                    movementLines[key] = L.polyline(latlngs, lineOpts).addTo(map);
                  } else {
                    line.setLatLngs(latlngs);
                    line.setStyle(lineOpts);
                  }
                } else {
                  if (circle){ map.removeLayer(circle); delete movementCircles[key]; }
                  // Remove movement line if threshold not exceeded
                  if (movementLines[key]){ 
                    map.removeLayer(movementLines[key]); 
                    delete movementLines[key]; 
                  }
                }
                
                // Draw lines to all gateway connections from the backend
                if (appFeatures.show_gateways && node.is_special && node.lat != null && node.lon != null && node.gateway_connections) {
                  var connections = node.gateway_connections;
                  
                  for (var gc = 0; gc < connections.length; gc++) {
                    var gwConnection = connections[gc];
                    var gwId = gwConnection.id;
                    var gwLat = gwConnection.lat;
                    var gwLon = gwConnection.lon;
                    var isBestGateway = node.best_gateway && node.best_gateway.id === gwId;
                    
                    if (gwLat != null && gwLon != null) {
                      var lineKey = 'gw_' + node.id + '_' + gwId;
                      var lineOpts = {
                        color: isBestGateway ? '#FF9800' : '#FFB74D',  // Brighter orange for current, dimmer for historical
                        weight: isBestGateway ? 2 : 1,
                        opacity: isBestGateway ? 0.7 : 0.4,
                        dashArray: '3, 5'  // Dotted line
                      };
                      var latlngs = [[node.lat, node.lon], [gwLat, gwLon]];
                      
                      if (!gatewayLines[lineKey]) {
                        gatewayLines[lineKey] = L.polyline(latlngs, lineOpts).addTo(map);
                      } else {
                        gatewayLines[lineKey].setLatLngs(latlngs);
                        gatewayLines[lineKey].setStyle(lineOpts);
                      }
                      
                      // Update popup with gateway info
                      var rssiStr = gwConnection.rssi !== undefined ? ' RSSI:' + gwConnection.rssi : '';
                      var snrStr = gwConnection.snr !== undefined ? ' SNR:' + gwConnection.snr.toFixed(2) : '';
                      var popup = 'Signal: ' + gwConnection.name + rssiStr + snrStr;
                      gatewayLines[lineKey].bindPopup(popup);
                    }
                  }
                } else if (!appFeatures.show_gateways) {
                  // Remove all gateway lines for this node if feature is disabled
                  for (var lineKey in gatewayLines) {
                    if (lineKey.indexOf('gw_' + node.id + '_') === 0) {
                      map.removeLayer(gatewayLines[lineKey]);
                      delete gatewayLines[lineKey];
                    }
                  }
                }
              }
            }
            
            if (appFeatures.show_position_trails){
              for(var t=0; t<toMap.length; t++){
                var sn = toMap[t]; 
                if(!sn.is_special) continue;
                (function(node){
                  var hours = parseInt(appFeatures.trail_history_hours || '24', 10);
                  makeApiRequest('GET', 'api/special/history?node_id=' + node.id + '&hours=' + hours, function(xhr2){
                    if (xhr2.status === 200){
                      try { 
                        var h = JSON.parse(xhr2.responseText); 
                        var pts = h.points || []; 
                        if (trails[node.id]) { 
                          map.removeLayer(trails[node.id]); 
                          delete trails[node.id]; 
                        } 
                        if (pts.length >= 2){ 
                          var latlngs = []; 
                          for(var u=0;u<pts.length;u++){ 
                            var pnt = pts[u]; 
                            latlngs.push([pnt.lat, pnt.lon]); 
                          } 
                          trails[node.id] = L.polyline(latlngs, {color:'#1976D2', weight:3, opacity:0.7}).addTo(map); 
                        } else {
                          console.log('No trail data for node', node.id, pts);
                        }
                      } catch(e){ 
                        console.warn('Error parsing trail history for node', node.id, e);
                      }
                    } else {
                      console.warn('Trail API request failed for node', node.id, xhr2.status);
                    }
                  });
                })(sn);
              }
            } else { 
              for (var tk in trails){ 
                if(trails.hasOwnProperty(tk)){ 
                  map.removeLayer(trails[tk]); 
                  delete trails[tk]; 
                } 
              } 
            }
          }
        });
    } catch(e){ 
      console.error('Update error:', e); 
    }
  }

  function updateStatus(){
    try {
      var statusEl = document.getElementById('mqtt-status');
      if (!statusEl) return;
      
      makeApiRequest('GET', 'api/status', function(xhr){ 
        try {
          if (xhr.status === 200){ 
            // Connection restored
            window.connectionLost = false;
              hideConnectionBanner();
            var data2 = JSON.parse(xhr.responseText); 
            var txt = '❌ Disconnected';
            if (data2 && data2.mqtt_status === 'receiving_packets') {
              txt = '✅ Receiving packets';
            } else if (data2 && data2.mqtt_status === 'connected_to_server') {
              txt = '🔗 Connected to server';
            } else if (data2 && data2.mqtt_status === 'connecting') {
              txt = '⏳ Connecting...';
            }
            statusEl.textContent = txt;
          } else if (xhr.status === 429) {
            pausePollingForRateLimit();
            statusEl.textContent = '⏸️ Rate limited (paused 60s)';
          } else if (xhr.status === 0) {
            // Network error - server unreachable
            window.connectionLost = true;
              showConnectionBanner();
            statusEl.textContent = '❌ Server Unreachable';
          }
        } catch(e) {
          // Silent catch - don't let callback errors propagate
        }
      });
    } catch(e) {
      // Silent - don't let updateStatus errors break the poll loop
      console.error('[STATUS] Error calling updateStatus:', e);
    }
  }

  window.showRecent = function(){
    try { 
      makeApiRequest('GET', 'api/recent_messages', function(xhr){ 
        if (xhr.status !== 200){ 
          alert('Failed to fetch recent messages'); 
          return; 
        } 
        try { 
          var data = JSON.parse(xhr.responseText); 
          var pretty = JSON.stringify(data, null, 2); 
          var blob = new Blob([pretty], {type:'application/json'}); 
          var url = URL.createObjectURL(blob); 
          window.open(url, '_blank'); 
        } catch(e){ 
          alert('Failed to parse recent messages'); 
        } 
      }); 
    } catch(e){ 
      alert('Error fetching recent messages'); 
    }
  };
  
  window.centerNode = function(lat, lon){ 
    if (map) map.setView([lat, lon], 13);
    // On mobile, close sidebar when clicking a node to show the map
    if (window.innerWidth <= 768) {
      var sidebar = document.getElementById('sidebar');
      if (sidebar && sidebar.classList.contains('visible')) {
        sidebar.classList.remove('visible');
        var overlay = document.getElementById('sidebar-overlay');
        if (overlay) overlay.style.display = 'none';
      }
    }
  };


  // initChannels removed: channel filter no longer used
  initMap(); 
  
  loadAppFeatures(); // Load app features from server config
  updateStatus(); // Call immediately to get initial status
  
  // Initial fetch on page load
  try {
    updateNodes();
  } catch(e) {
    console.error('[INIT] Error in updateNodes:', e);
  }
  
  var statusRefresh = parseInt(document.body.dataset.statusRefresh || '60000', 10);
  var nodeRefresh = parseInt(document.body.dataset.nodeRefresh || '60000', 10);
  
  // Rate limit pause state
  var rateLimitPauseUntil = 0;  // Timestamp when rate limit pause ends
  var rateLimitPauseInterval = 60000;  // Pause for 60 seconds after hitting limit
  
  // Polling progress state
  var lastPollTime = Date.now();
  var progressInterval = null;
  
  function updateRefreshProgress() {
    try {
      var now = Date.now();
      var timeSinceLastPoll = now - lastPollTime;
      var progress = (timeSinceLastPoll / statusRefresh) * 100;
      
      // Update progress bar width and color
      var progressBar = document.getElementById('refresh-progress-bar');
      if (progressBar) {
        progressBar.style.width = Math.min(progress, 100) + '%';
        
        // Determine color based on connection and rate limit state
        if (window.connectionLost) {
          // Gray when connection is lost
          progressBar.style.background = '#999';
          progressBar.style.boxShadow = 'none';
          showConnectionBanner();
        } else if (isRateLimitPaused()) {
          // Red when rate limited
          progressBar.style.background = '#f44336';
          progressBar.style.boxShadow = '0 0 10px rgba(244, 67, 54, 0.8)';
        } else {
          // White normally
          progressBar.style.background = 'white';
          progressBar.style.boxShadow = 'none';
          hideConnectionBanner();
        }
      }
    } catch(e) {
      console.error('[PROGRESS] Error updating refresh progress:', e);
    }
  }
  
  function isRateLimitPaused() {
    return Date.now() < rateLimitPauseUntil;
  }
  
  function pausePollingForRateLimit() {
    rateLimitPauseUntil = Date.now() + rateLimitPauseInterval;
    console.warn('[RATELIMIT] Pausing polls for 60 seconds');
  }
  
  // Poll status continuously every 500ms to ensure live updates
  var statusPollInterval = null;
  var pollAttempts = 0;
  
  function startStatusPolling(){
    try {
      if (statusPollInterval) {
        clearInterval(statusPollInterval);
      }
      pollAttempts = 0;
      
      statusPollInterval = setInterval(function() {
        try {
          // Skip polling if rate limited
          if (isRateLimitPaused()) {
            console.log('[RATELIMIT] Skipping poll - paused until', new Date(rateLimitPauseUntil).toLocaleTimeString());
            return;
          }
          pollAttempts++;
          lastPollTime = Date.now();  // Reset poll timer
          updateStatus();
        } catch(e) {
          console.error('Error in polling:', e);
        }
      }, statusRefresh);
    } catch(e) {
      console.error('Error starting polling:', e);
    }
  }
  
  try {
    startStatusPolling();
  } catch(e) {
    console.error('Error starting polling:', e);
  }
  
  // Start node polling
  try {
    setInterval(function(){ 
      try {
        updateNodes(); 
      } catch(e) {
        console.error('Error in node polling:', e);
      }
    }, nodeRefresh);
  } catch(e) {
    console.error('Error setting up node polling:', e);
  }
  
  // Update voltage graphs every polling interval
  try {
    setInterval(function(){
      try {
        // updateVoltageGraphs() function not defined yet - skipping
      } catch(e) {
        console.error('[VOLT] Error updating voltage graphs:', e);
      }
    }, statusRefresh);
  } catch(e) {
    console.error('[INIT] Error setting up voltage polling:', e);
  }
  
  // Update refresh progress bar every 100ms
  try {
    progressInterval = setInterval(function() {
      updateRefreshProgress();
    }, 100);
  } catch(e) {
    console.error('[INIT] Error setting up progress bar:', e);
  }
  
  // Handle iOS Safari zoom issues with fixed position FAB button
  // iOS Safari can detach fixed elements during zoom - this keeps it visible
  try {
    var fab = document.getElementById('menu-fab');
    if (fab) {
      // Add will-change and transform to help Safari keep element in viewport during zoom
      fab.style.willChange = 'transform';
      fab.style.webkitTransform = 'translate3d(0, 0, 0)';
      
      // Re-anchor to viewport after zoom/scroll events
      var reanchorFAB = function() {
        if (fab && fab.parentNode) {
          // Force reflow to re-anchor
          void fab.offsetWidth;
        }
      };
      
      // Listen for zoom/scroll/resize
      window.addEventListener('resize', reanchorFAB);
      document.addEventListener('scroll', reanchorFAB, { passive: true });
      window.addEventListener('orientationchange', reanchorFAB);
      
      // Also check periodically in case we miss an event
      setInterval(reanchorFAB, 2000);
    }
  } catch(e) {
    console.error('[UI] Error setting up FAB:', e);
  }
  
  // Handle orientation changes - fix map rendering and sidebar state
  var handleOrientationChange = function() {
    // Small delay to allow viewport to settle after orientation change
    setTimeout(function() {
      // Invalidate map size if map exists
      if (map && typeof map.invalidateSize === 'function') {
        map.invalidateSize();
      }
      
      // On landscape (wider than tall), auto-hide sidebar on mobile
      var isLandscape = window.innerWidth > window.innerHeight;
      var isMobile = window.innerWidth <= 768;
      var sidebar = document.getElementById('sidebar');
      var overlay = document.getElementById('sidebar-overlay');
      
      if (isMobile && isLandscape && sidebar && sidebar.classList.contains('visible')) {
        // Auto-close sidebar in landscape to maximize map view
        sidebar.classList.remove('visible');
        if (overlay) overlay.style.display = 'none';
      }
      
      // Also hide overlay if we're not in mobile mode anymore
      if (!isMobile && overlay) {
        overlay.style.display = 'none';
      }
      
      // Force reflow
      if (sidebar) {
        void sidebar.offsetWidth;
      }
    }, 100);
  };
  
  window.addEventListener('orientationchange', handleOrientationChange);
  window.addEventListener('resize', function() {
    // Throttle resize handler
    clearTimeout(window.resizeTimeout);
    window.resizeTimeout = setTimeout(function() {
      if (map && typeof map.invalidateSize === 'function') {
        map.invalidateSize();
      }
    }, 100);
  });
  
  // Attach hover tooltips to histogram points
  function attachHistogramTooltips(container) {
    var points = container.querySelectorAll('.histogram-point, .histogram-hover');
    var tooltip = null;
    
    points.forEach(function(point) {
      point.addEventListener('mouseenter', function(e) {
        var tooltipText = this.getAttribute('data-tooltip');
        if (!tooltipText) return;
        
        // Remove old tooltip if exists
        if (tooltip && tooltip.parentNode) {
          tooltip.parentNode.removeChild(tooltip);
        }
        
        // Create new tooltip with multiline formatting
        tooltip = document.createElement('div');
        tooltip.style.cssText = 'position:fixed;background:#333;color:white;padding:8px 10px;border-radius:4px;font-size:0.75em;z-index:10000;pointer-events:none;white-space:pre-line;box-shadow:0 2px 8px rgba(0,0,0,0.3);max-width:180px;line-height:1.4;';
        tooltip.textContent = tooltipText;
        document.body.appendChild(tooltip);
        
        // Position tooltip near cursor, above the point
        var rect = this.getBoundingClientRect();
        tooltip.style.left = Math.max(10, rect.left + rect.width / 2 - tooltip.offsetWidth / 2) + 'px';
        tooltip.style.top = (rect.top - tooltip.offsetHeight - 8) + 'px';
      });
      
      point.addEventListener('mouseleave', function() {
        if (tooltip && tooltip.parentNode) {
          tooltip.parentNode.removeChild(tooltip);
          tooltip = null;
        }
      });
    });
  }
  
  // Modal functions for node details
  window.showNodeDetails = function(nodeId, nodeName) {
    var modal = document.getElementById('nodeDetailsModal');
    var title = document.getElementById('modalTitle');
    var container = document.getElementById('histogramContainer');
    
    if (!modal) return;
    
    title.textContent = 'Signal History: ' + nodeName;
    container.innerHTML = '<div style="color:#999;">Loading signal history...</div>';
    modal.style.display = 'flex';
    
    // Fetch signal history from API for other nodes
    var url = '/api/signal/history?node_id=' + nodeId;
    var fetchOptions = {};
    if (apiKey) {
      fetchOptions.headers = {
        'Authorization': 'Bearer ' + apiKey
      };
    }
    
    fetch(url, fetchOptions)
      .then(function(response) {
        if (response.status === 401) {
          throw new Error('Unauthorized');
        }
        return response.json();
      })
      .then(function(data) {
        if (data.points && data.points.length > 0) {
          var svg = buildSignalHistogramSVG(data.points);
          container.innerHTML = svg;
          attachHistogramTooltips(container);
        } else {
          container.innerHTML = '';
          var emptyDiv = document.createElement('div');
          emptyDiv.style.cssText = 'color:#999;padding:20px;';
          emptyDiv.textContent = 'No signal history available yet.';
          container.appendChild(emptyDiv);
        }
      })
      .catch(function(error) {
        console.error('[MODAL] Error fetching signal history:', error);
        container.innerHTML = '';
        var errorDiv = document.createElement('div');
        errorDiv.style.cssText = 'color:#d32f2f;padding:20px;';
        errorDiv.textContent = 'Error loading signal history: ' + error.message;
        container.appendChild(errorDiv);
      });
  };
  
  window.closeNodeDetails = function() {
    var modal = document.getElementById('nodeDetailsModal');
    if (modal) {
      modal.style.display = 'none';
    }
  };
  
  // Close modal on ESC key
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
      window.closeNodeDetails();
    }
  });
  
  // Close modal on backdrop click
  document.getElementById('nodeDetailsModal').addEventListener('click', function(e) {
    if (e.target === this) {
      window.closeNodeDetails();
    }
  });
})();






