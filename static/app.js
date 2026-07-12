/* Buoy Tracker Client Script (ES5) */
(function(){
    // Utility: Debounce function to limit how often a function can fire
    // Waits for quiet period before executing (prevents spam on rapid events like keystrokes)
    function debounce(func, wait) {
      var timeout;
      return function() {
        var context = this, args = arguments;
        clearTimeout(timeout);
        timeout = setTimeout(function() {
          func.apply(context, args);
        }, wait);
      };
    }

    // ============================================================================
    // HELPER FUNCTIONS - Reusable utilities to reduce code duplication
    // ============================================================================

    /**
     * Calculate distance between two lat/lon points using Haversine formula
     * @param {number} lat1 - Latitude of first point
     * @param {number} lon1 - Longitude of first point
     * @param {number} lat2 - Latitude of second point
     * @param {number} lon2 - Longitude of second point
     * @returns {number} Distance in meters
     */
    function calculateDistance(lat1, lon1, lat2, lon2) {
      var R = 6371; // Earth's radius in km
      var lat1Rad = (lat1 * Math.PI) / 180;
      var lon1Rad = (lon1 * Math.PI) / 180;
      var lat2Rad = (lat2 * Math.PI) / 180;
      var lon2Rad = (lon2 * Math.PI) / 180;
      var dlat = lat2Rad - lat1Rad;
      var dlon = lon2Rad - lon1Rad;
      var a = Math.sin(dlat / 2) * Math.sin(dlat / 2) +
              Math.cos(lat1Rad) * Math.cos(lat2Rad) *
              Math.sin(dlon / 2) * Math.sin(dlon / 2);
      var c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
      return Math.round(R * c * 1000); // Return meters
    }

    /**
     * Format server-provided voltage and battery percentage as "4.00V (82%)".
     * Both values come from the server's single _estimate_battery_from_voltage curve;
     * the client never converts.
     */
    function formatBattery(voltage, batteryPct) {
      if (voltage != null && batteryPct != null) {
        return voltage.toFixed(2) + 'V (' + batteryPct + '%)';
      }
      if (voltage != null) return voltage.toFixed(2) + 'V';
      if (batteryPct != null) return batteryPct + '%';
      return null;
    }

    /**
     * Format timestamp for display
     * @param {number} epochSeconds - Unix timestamp in seconds
     * @returns {string} Formatted date string
     */
    function formatTimestamp(epochSeconds) {
      return new Date(epochSeconds * 1000).toLocaleString();
    }

    /**
     * Format time ago in human readable format (e.g. "5m ago", "2h ago")
     * @param {number} epochSeconds - Unix timestamp in seconds
     * @returns {string} Human readable time ago string
     */
    function formatTimeAgo(epochSeconds) {
      var now = Date.now() / 1000;
      var age = Math.round(now - epochSeconds);
      if (age < 60) return age + 's';
      if (age < 3600) return Math.floor(age / 60) + 'm';
      return Math.floor(age / 3600) + 'h';
    }

    /**
     * Build popup text for trail position marker
     * @param {object} point - Position point with lat, lon, ts, battery, rssi, snr
     * @param {number} index - Index of this point in trail
     * @param {number} total - Total number of points
     * @param {object} node - Node object with origin_lat, origin_lon
     * @returns {string} HTML popup text
     */
    function buildTrailPopup(point, index, total, node) {
      // Assumes point.lat/lon are real — the one call site below already
      // filters special_history for position-bearing points before this
      // runs. Don't call this with an unfiltered point.
      var lines = [];

      lines.push('<b>' + escapeHtml(node.name) + '</b>');

      // Position info
      var posText = 'Pos #' + (index + 1) + ' / ' + total;
      if (index === 0) posText += ' (OLDEST)';
      if (index === total - 1) posText += ' (NEWEST)';
      lines.push(posText);

      // Timestamp
      if (point.ts) {
        lines.push('Time: ' + formatTimestamp(point.ts));
      }

      // Coordinates
      lines.push('Lat: ' + point.lat.toFixed(6));
      lines.push('Lon: ' + point.lon.toFixed(6));

      // Distance to home
      if (node.origin_lat != null && node.origin_lon != null) {
        var distM = calculateDistance(node.origin_lat, node.origin_lon, point.lat, point.lon);
        lines.push('Distance to home: ' + distM + ' M');
      }

      var batteryStr = formatBattery(point.voltage, point.battery_pct);
      if (batteryStr) {
        lines.push('Battery: ' + batteryStr);
      }


      return lines.join('<br>');
    }

    /**
     * Create marker style options based on position in trail
     * Size gradient: newest (last) = largest, oldest (first) = smallest
     * @param {number} index - Index of point in trail
     * @param {number} total - Total points in trail
     * @returns {object} Leaflet marker style options
     */
    function getTrailMarkerStyle(index, total) {
      // Size increases from 5px (oldest) to 12px (newest)
      // Color fades from light blue (oldest) to dark blue (newest)
      var ratio = total > 1 ? (index / (total - 1)) : 1;
      var radius = 5 + (ratio * 7);  // 5-12px range

      // Color gradient: #90CAF9 (light blue, oldest) to #1976D2 (dark blue, newest)
      var r = Math.round(144 + (ratio * (25 - 144)));  // 144 -> 25
      var g = Math.round(202 + (ratio * (118 - 202))); // 202 -> 118
      var b = Math.round(249 + (ratio * (210 - 249))); // 249 -> 210
      var fillColor = 'rgb(' + r + ',' + g + ',' + b + ')';

      return {
        radius: radius,
        fillColor: fillColor,
        color: fillColor,
        weight: 2,
        opacity: 0.8,
        fillOpacity: 0.6
      };
    }


    /**
     * Calculate age-based traffic light color and text
     * @param {number} timestamp - Unix timestamp in seconds
     * @param {number} greenThreshold - Max age (seconds) for green status
     * @param {number} yellowThreshold - Max age (seconds) for yellow status
     * @returns {object} {color: 'green'|'yellow'|'red'|'gray', text: '5s'|'3m'|'2h'|'?'}
     */
    function getAgeStatus(timestamp, greenThreshold, yellowThreshold) {
      if (timestamp == null || timestamp <= 0) return {color: 'gray', text: '—'};
      var now = Date.now() / 1000;
      var age = Math.round(now - timestamp);
      var color = age < greenThreshold ? 'green' : age < yellowThreshold ? 'yellow' : 'red';
      var text = formatTimeAgo(timestamp);
      return {color: color, text: text};
    }

    /**
     * Calculate battery traffic light color
     * @param {number} batteryPct - Battery percentage (0-100)
     * @param {number} voltage - Battery voltage
     * @returns {string} 'green'|'yellow'|'red'|'gray'
     */
    function getBatteryColor(batteryPct, voltage) {
      if (batteryPct !== null) {
        if (voltage !== null) {
          // Have both: use combined check
          if (batteryPct >= 70 && voltage >= 3.7) return 'green';
          if (batteryPct >= 40 && voltage >= 3.5) return 'yellow';
          return 'red';
        } else {
          // Have battery but not voltage
          if (batteryPct >= 70) return 'green';
          if (batteryPct >= 40) return 'yellow';
          return 'red';
        }
      } else if (voltage !== null) {
        // Have voltage but not battery percentage
        if (voltage >= 3.7) return 'green';
        if (voltage >= 3.5) return 'yellow';
        return 'red';
      }
      return 'gray';
    }


    /**
     * Build map marker popup HTML for a node
     * @param {object} node - Node data object
     * @param {object} displayInfo - Display information {name, label, stale, noFix, short, channel}
     * @returns {string} HTML popup content
     */
    function buildMapPopup(node, displayInfo) {
      var popup = '<b>' + escapeHtml(displayInfo.name) + '</b>' + displayInfo.label + displayInfo.stale + displayInfo.noFix + '<br>' + escapeHtml(displayInfo.short);

      // Node ID in decimal and hex
      var nodeIdHex = '!' + node.id.toString(16).padStart(8, '0');
      popup += '<br>ID: ' + node.id + ' (' + nodeIdHex + ')';

      var batteryStr = formatBattery(node.voltage, node.battery_pct);
      if (batteryStr) {
        popup += '<br>Battery: ' + batteryStr;
        if (node.battery_low) popup += ' ⚠️ LOW';
      } else {
        popup += '<br>Battery: ?';
      }

      // Channel
      if (displayInfo.channel) {
        popup += '<br>Channel: ' + escapeHtml(displayInfo.channel);
      }

      // Hardware model
      if (node.hw_model && node.hw_model !== 'Unknown') {
        popup += '<br>Hardware: ' + escapeHtml(node.hw_model);
      }

      // Role
      if (node.role && node.role !== 'Unknown') {
        popup += '<br>Role: ' + escapeHtml(node.role.replace('CLIENT_', ''));
      }

      // Gateway: Show which special nodes it's receiving from
      if (node.is_gateway) {
        var specialNodesReceivingViaThis = [];
        var allSpecialNodes = currentNodesData || [];
        for (var snIdx = 0; snIdx < allSpecialNodes.length; snIdx++) {
          var specialNode = allSpecialNodes[snIdx];
          if (specialNode.is_special && specialNode.gateway_connections) {
            for (var gwIdx = 0; gwIdx < specialNode.gateway_connections.length; gwIdx++) {
              var gw = specialNode.gateway_connections[gwIdx];
              if (gw.id === node.id) {
                specialNodesReceivingViaThis.push({
                  name: specialNode.name,
                  rssi: gw.rssi,
                  snr: gw.snr,
                  hops_traveled: (gw.hop_start !== undefined && gw.hop_limit !== undefined) ? (gw.hop_start - gw.hop_limit) : null,
                  is_best: specialNode.best_gateway && specialNode.best_gateway.id === node.id
                });
                break;
              }
            }
          }
        }

        if (specialNodesReceivingViaThis.length > 0) {
          popup += '<br><hr style="margin:3px 0;"><span style="font-weight:bold;">📶 Receiving from:</span>';
          for (var snrIdx = 0; snrIdx < specialNodesReceivingViaThis.length; snrIdx++) {
            var snConnection = specialNodesReceivingViaThis[snrIdx];
            var bestMarker = snConnection.is_best ? ' ⭐' : '';
            var hopInfo = snConnection.hops_traveled !== null ? ' (' + snConnection.hops_traveled + 'h)' : '';
            popup += '<br>├─ ' + escapeHtml(snConnection.name) + hopInfo + bestMarker;
          }
        }
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
          if (node.anchor_spread_m != null) {
            popup += '<br>Anchor swing (7d): σ ' + node.anchor_spread_m.toFixed(1) + ' m · ' +
                     node.anchor_spread_n + ' fixes';
          }
        }

        // Time indicators
        if (node.last_position_update != null) {
          popup += '<br>Last Position Update: ' + formatTimeAgo(node.last_position_update) + ' ago';
        }
        if (node.last_seen != null) {
          popup += '<br>Sign of Life: ' + formatTimeAgo(node.last_seen) + ' ago';
        }
      }

      // All gateway connections (only for special nodes)
      if (node.is_special && node.gateway_connections && node.gateway_connections.length > 0) {
        popup += '<br><hr style="margin:3px 0;"><span style="font-weight:bold;">📡 First-hop Gateways:</span>';
        for (var gwPopupIdx = 0; gwPopupIdx < node.gateway_connections.length; gwPopupIdx++) {
          var gwConn = node.gateway_connections[gwPopupIdx];
          var isBest = node.best_gateway && node.best_gateway.id === gwConn.id;
          var bestMarker = isBest ? ' ⭐' : '';

          var noPos = (gwConn.lat == null || gwConn.lon == null) ? ' 📍?' : '';
          popup += '<br>├─ ' + escapeHtml(gwConn.name) + noPos + bestMarker;
        }
      }

      // Add link to liamcottle meshview server
      popup += '<br><a href="https://meshtastic.liamcottle.net/?node_id=' + node.id + '" target="_blank" style="color:#2196F3;">View on Meshtastic Map</a>';

      return popup;
    }

    // Tab switching logic for menu: Legend/Controls
    var settingsInitialized = false;
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
        // Trying to access Controls - check auth first if required
        if (apiKeyRequired && !isLocalhost && !apiKey) {
          // Don't show controls tab, go back to legend
          legendTabBtn.classList.add('active');
          legendTabBtn.classList.add('tab-legend');
          controlsTabBtn.classList.remove('active');
          controlsTabBtn.classList.remove('tab-controls');
          tabLegend.style.display = 'block';
          tabControls.style.display = 'none';
          // Show auth modal
          showApiKeyModal();
          return;
        }
        legendTabBtn.classList.remove('active');
        legendTabBtn.classList.remove('tab-legend');
        controlsTabBtn.classList.add('active');
        controlsTabBtn.classList.add('tab-controls');
        tabLegend.style.display = 'none';
        tabControls.style.display = 'block';
        // Only initialize settings once per menu session
        if (!settingsInitialized) {
          setTimeout(initSettingsInputs, 100);
          settingsInitialized = true;
        }
      }
    };

    // Initialize settings inputs with config values from /health
    // Helper to set input values from config
    function setInputValue(elementId, value, isCheckbox) {
      var el = document.getElementById(elementId);
      if (el) {
        if (isCheckbox) {
          el.checked = value;
        } else {
          el.value = value;
        }
      }
    }

    function initSettingsInputs() {
      makeApiRequest('GET', 'health', function(xhr) {
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

        // Initialize input values using helper
        setInputValue('showGatewaysInput', controls.show_gateways, true);
        setInputValue('showPositionTrailsInput', controls.show_position_trails, true);
        setInputValue('showNauticalMarkersInput', controls.show_nautical_markers, true);
        setInputValue('trailHistoryInput', controls.trail_history_hours, false);
        setInputValue('lowBatteryInput', controls.low_battery_threshold, false);
        setInputValue('movementThresholdInput', controls.movement_threshold, false);
        setInputValue('apiPollingInput', controls.api_polling_interval, false);

        // Wire up listeners to update UI state and persist to backend
        // show_all_nodes removed - now config-only setting
        document.getElementById('showGatewaysInput').onchange = function(e) {
          var newValue = e.target.checked;
          appFeatures.show_gateways = newValue;

          // Update backend setting and reload MQTT subscriptions
          makeApiRequest('POST', 'api/config/show-gateways', function(xhr) {
            if (xhr.status === 200 || xhr.status === 207) {
              var response = JSON.parse(xhr.responseText);
              if (response.subscriptions_reloaded) {
                console.log('[CONFIG] show_gateways updated and MQTT subscriptions reloaded');
              } else if (response.warning) {
                console.warn('[CONFIG] ' + response.warning);
              }
            } else {
              console.error('[CONFIG] Failed to update show_gateways on backend');
            }
          }, JSON.stringify({show_gateways: newValue}));

          // Update legend visibility
          var trafficLightLegend = document.getElementById('trafficLightLegend');
          updateLegendVisibility();
          updateNodes();
        };
        document.getElementById('showPositionTrailsInput').onchange = function(e) {
          appFeatures.show_position_trails = e.target.checked;
          updateLegendVisibility();
          updateNodes();
        };
        document.getElementById('showNauticalMarkersInput').onchange = function(e) {
          appFeatures.show_nautical_markers = e.target.checked;
          applyNauticalOverlay();
          updateNodes();
        };

        // Debounce: wait 500ms after user stops typing before updating
        document.getElementById('trailHistoryInput').oninput = debounce(function(e) {
          appFeatures.trail_history_hours = Number(e.target.value);
          updateNodes();
        }, 500);
        document.getElementById('lowBatteryInput').onchange = function(e) {
          var newThreshold = parseInt(e.target.value);
          if (newThreshold > 0 && newThreshold <= 100) {
            makeApiRequest('POST', 'api/config/battery-threshold', function(xhr) {
              if (xhr.status === 200) {
                appFeatures.low_battery_threshold = newThreshold;
                updateNodes();
              } else {
                console.error('Failed to update battery threshold');
                initSettingsInputs();
              }
            }, JSON.stringify({threshold: newThreshold}));
          }
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
        // Debounce: wait 500ms after user stops typing before updating polling
        document.getElementById('apiPollingInput').oninput = debounce(function(e) {
          appFeatures.api_polling_interval = Number(e.target.value);
          // Restart polling with new interval
          if (window.pollingTimer) {
            clearInterval(window.pollingTimer);
          }
          startPolling();
        }, 500);
      });
    }

    // Call initSettingsInputs when menu opens (for Controls tab only)
    var origToggleMenu = window.toggleMenu;
    window.toggleMenu = function() {
      origToggleMenu();
      var modal = document.getElementById('menu-modal');
      // Reset settings initialization flag when menu opens
      settingsInitialized = false;
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
  var urlPrefix = document.body.dataset.urlPrefix || '';  // URL prefix for subpath deployments (e.g., '/buoy-tracker')
  var modalShownRecently = false; // Prevent rapid modal re-displays
  var authCheckDisabled = false; // Disable 401 checks briefly after login attempt
  var pendingAuthRequest = null; // Last admin request that failed with 401 — replayed after login
  
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
        
        // Refresh data with new key and replay the action that hit the 401,
        // so the user does not have to click it a second time
        var pending = pendingAuthRequest;
        pendingAuthRequest = null;
        setTimeout(function() {
          updateStatus();
          updateNodes();
          loadAlertStatus();
          if (pending) {
            makeApiRequest(pending.method, pending.url, pending.callback, pending.body);
          }
        }, 100);
      }
    };
    
    clearBtn.onclick = function() {
      input.value = '';
      apiKey = '';
      localStorage.removeItem('tracker_api_key');
      if (modal) modal.style.display = 'none';
      // Force auth check on next Control Menu access
      authCheckDisabled = false;
    };
    
    // Allow Enter key to submit
    input.onkeypress = function(e) {
      if (e.key === 'Enter') {
        submitBtn.click();
      }
    };
  }
  
  // Alerts button styling via design-system classes (no inline hex)
  function setAlertsButton(enabled) {
    var btn = document.getElementById('toggleAlertsBtn');
    var status = document.getElementById('alertStatus');
    if (btn) {
      btn.className = enabled ? 'btn good' : 'btn crit';
      btn.textContent = enabled ? 'Alert emails: on' : 'Alert emails: off';
    }
    if (status) status.textContent = enabled
      ? 'Alerts are ON — movement/battery emails will be sent'
      : 'Alerts are OFF — no emails will be sent';
  }

  // Toggle email alerts on/off
  window.toggleAlerts = function toggleAlerts() {
    try {
      makeApiRequest('POST', 'api/alerts/toggle', function(xhr) {
        try {
          if (xhr.status === 200) {
            var data = JSON.parse(xhr.responseText);
            setAlertsButton(data.alerts_enabled);
            
            console.log('[Alerts] Toggled: ' + (data.alerts_enabled ? 'ON' : 'OFF'));
          } else {
            alert('Failed to toggle alerts: ' + xhr.statusText);
          }
        } catch(e) {
          console.error('Error parsing alert toggle response:', e);
          alert('Error toggling alerts');
        }
      });
    } catch(e) {
      console.error('API request error:', e);
      alert('Failed to toggle alerts');
    }
  }
  
  // Load alert status on page initialization
  function loadAlertStatus() {
    try {
      makeApiRequest('GET', 'api/alerts/status', function(xhr) {
        try {
          if (xhr.status === 200) {
            var data = JSON.parse(xhr.responseText);
            setAlertsButton(data.alerts_enabled);
          }
        } catch(e) {
          // Silent - use default state
        }
      });
    } catch(e) {
      // Silent - use default state
    }
  }
  
  // -------------------------------------------------------------------
  // Per-buoy movement-alert mutes (v2.0 Phase 1)
  // Mute state arrives with each node in /api/nodes (movement_alerts_muted);
  // the Controls-tab list renders from the latest special-node snapshot.
  // -------------------------------------------------------------------
  var lastSpecialNodes = [];

  function renderMuteList() {
    var el = document.getElementById('muteList');
    if (!el) return;
    if (!lastSpecialNodes.length) {
      el.textContent = 'No special nodes seen yet.';
      return;
    }
    var html = '';
    lastSpecialNodes.forEach(function(n) {
      var muted = !!n.movement_alerts_muted;
      var label = n.special_label || n.name || String(n.id);
      html += '<div style="display:flex;justify-content:space-between;align-items:center;margin:3px 0;">' +
              '<span>' + escapeHtml(label) + '</span>' +
              '<button onclick="toggleMute(' + n.id + ')" style="border:none;border-radius:4px;cursor:pointer;padding:3px 10px;color:#fff;font-weight:bold;background:' + (muted ? '#f44336' : '#4CAF50') + ';">' +
              (muted ? '🔕 Muted' : '🔔 Active') + '</button></div>';
    });
    el.innerHTML = html;
  }

  window.toggleMute = function toggleMute(nodeId) {
    var node = null;
    for (var i = 0; i < lastSpecialNodes.length; i++) {
      if (lastSpecialNodes[i].id === nodeId) { node = lastSpecialNodes[i]; break; }
    }
    var newMuted = node ? !node.movement_alerts_muted : true;
    try {
      makeApiRequest('POST', 'api/alerts/mute', function(xhr) {
        if (xhr.status === 200) {
          if (node) node.movement_alerts_muted = newMuted;
          renderMuteList();
          console.log('[Mute] node ' + nodeId + ' -> ' + (newMuted ? 'muted' : 'active'));
        } else if (xhr.status !== 401) {
          alert('Failed to update mute: ' + xhr.statusText);
        }
      }, JSON.stringify({ node_id: nodeId, muted: newMuted }));
    } catch(e) {
      console.error('Mute toggle error:', e);
      alert('Failed to update mute');
    }
  };

  // Reset runtime settings to config-file defaults (deletes DB overrides)
  window.resetSettings = function resetSettings() {
    if (!confirm('Reset all runtime settings to the tracker.config defaults?')) {
      return;
    }
    try {
      makeApiRequest('POST', 'api/settings/reset', function(xhr) {
        if (xhr.status === 200) {
          console.log('[Settings] Reset to config defaults');
          // Reload so the UI re-reads thresholds and toggles from the server
          location.reload();
        } else if (xhr.status !== 401) {
          alert('Failed to reset settings: ' + xhr.statusText);
        }
      });
    } catch(e) {
      console.error('Settings reset error:', e);
      alert('Failed to reset settings');
    }
  };

  // Restart the server
  window.restartServer = function restartServer() {
    if (!confirm('Restart server? This will clear all trail data and briefly disconnect all clients. Are you sure?')) {
      return;
    }
    
    try {
      var btn = document.getElementById('restartServerBtn');
      var status = document.getElementById('restartStatus');
      
      if (btn) btn.disabled = true;
      if (status) status.textContent = 'Restarting server...';
      
      makeApiRequest('POST', 'api/server/restart', function(xhr) {
        try {
          if (xhr.status === 202 || xhr.status === 200) {
            if (status) status.textContent = 'Server is restarting... page will refresh automatically.';
            
            // Wait 3 seconds then try to reconnect
            setTimeout(function() {
              location.reload();
            }, 3000);
          } else {
            if (status) status.textContent = 'Error: ' + xhr.statusText;
            if (btn) btn.disabled = false;
          }
        } catch(e) {
          // Expected to fail since server is shutting down
          if (status) status.textContent = 'Server is restarting... page will refresh automatically.';
          setTimeout(function() {
            location.reload();
          }, 3000);
        }
      });
    } catch(e) {
      console.error('API request error:', e);
      alert('Failed to restart server');
      var btn = document.getElementById('restartServerBtn');
      if (btn) btn.disabled = false;
    }
  }
  
  var map = null;
  var markers = {};
  var gatewayMarkers = {}; // markers for gateways receiving special node packets
  var trails = {};
  var trail_markers = {}; // individual position history markers per node (node_id -> array of markers)
  var movementCircles = {}; // origin-anchored movement alert circles per node
  var thresholdRings = {}; // threshold rings around home positions for special nodes
  var movementLines = {}; // red lines from origin to current position when moved
  var gatewayLines = {}; // lines from special nodes to their best gateway receivers
  var currentNodesData = []; // All nodes from latest API fetch - used for gateway popup building
  
  // Ensure global scope access for debugging
  window.gatewayLines = gatewayLines;
  window.gatewayMarkers = gatewayMarkers;
  window.markers = markers;
  window.map = null; // Will be set when map initializes
  var gatewayConnections = {}; // persistent historical gateway connections per node: {nodeId: Set of gateway IDs}
  var movedAlertShown = {}; // track one-time alerts per node id

  // Helper function to make authenticated API requests
  function makeApiRequest(method, url, callback, body) {
    var origUrl = url;   // pre-prefix URL, for replay after login
    var sentWithKey = !!(apiKeyRequired && apiKey);
    try {
      // Prepend URL prefix for subpath deployments
      if (urlPrefix && !url.startsWith(urlPrefix)) {
        url = urlPrefix + '/' + url.replace(/^\//, '');
      }

      // Add cache-busting parameter (timestamp is sufficient, no need for random)
      if (method === 'GET') {
        var separator = (url.indexOf('?') === -1) ? '?' : '&';
        url += separator + '_t=' + Date.now();
      }

      var xhr = new XMLHttpRequest();
      xhr.timeout = 15000; // 15 second timeout for slow connections (was 5s)
      xhr.open(method, url, true);

      // Aggressive no-cache headers
      xhr.setRequestHeader('Cache-Control', 'no-cache, no-store, must-revalidate, max-age=0');
      xhr.setRequestHeader('Pragma', 'no-cache');
      xhr.setRequestHeader('Expires', '-1');

      // Set Content-Type for POST requests with body
      if (method === 'POST' && body) {
        xhr.setRequestHeader('Content-Type', 'application/json');
      }

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
            // Remember the rejected action so it can be replayed after login
            pendingAuthRequest = { method: method, url: origUrl, callback: callback, body: body };
            if (sentWithKey) {
              // The key we actually sent was rejected — it really is wrong
              apiKey = '';
              localStorage.removeItem('tracker_api_key');
            }
            // If no key was sent (first access), keep any stored key intact
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
              progressBar.style.background = 'var(--crit)';
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

      xhr.send(body || null);
    } catch(e) {
      console.error('API request error:', e);
      window.connectionLost = true;
      if (callback) callback({ status: 0, statusText: 'Network error' });
    }
  }
  
  // Configuration thresholds (in seconds) - will be loaded from server
  var statusBlueThreshold = 3600; // default: 1 hour (will be overwritten by config from API)
  var statusOrangeThreshold = 43200; // default: 12 hours (will be overwritten by config from API)
  
  // LPU (Last Position Update) thresholds - for GPS position packets (~2 hours apart)
  var lpuBlueThreshold = 10800; // default: 3 hours
  var lpuOrangeThreshold = 28800; // default: 8 hours
  
  // SoL (Sign of Life) thresholds - for any packet activity (more frequent)
  var solBlueThreshold = 7200; // default: 2 hours
  var solOrangeThreshold = 21600; // default: 6 hours
  
  // Signal quality thresholds
  
  var specialMovementThreshold = 50; // default: 50m (will be overwritten by config from API)
  
  // Load thresholds from server config on startup
  function loadConfigThresholds() {
    try {
      makeApiRequest('GET', 'health', function(xhr) {
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
              if (data.config.lpu_blue_threshold) {
                lpuBlueThreshold = data.config.lpu_blue_threshold;
              }
              if (data.config.lpu_orange_threshold) {
                lpuOrangeThreshold = data.config.lpu_orange_threshold;
              }
              if (data.config.sol_blue_threshold) {
                solBlueThreshold = data.config.sol_blue_threshold;
              }
              if (data.config.sol_orange_threshold) {
                solOrangeThreshold = data.config.sol_orange_threshold;
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
      if (apiKeyRequired) {
        initApiKeyModal();
        // DO NOT show modal here - only show when user tries to access Control Menu
        // Modal will appear on 401 response when accessing protected endpoints
      }
      // Set up tooltip event delegation (once on init, eliminates memory leak)
      setupTooltipDelegation();
      // Alert status loads when the Controls menu opens (avoids a 401
      // auth prompt at page load for remote viewers)
    });
  } else {
    // Already loaded
    if (apiKeyRequired) {
      initApiKeyModal();
      // DO NOT show modal here - only show when user tries to access Control Menu
      // Modal will appear on 401 response when accessing protected endpoints
    }
    // Set up tooltip event delegation (once on init, eliminates memory leak)
    setupTooltipDelegation();
    // Alert status loads when the Controls menu opens
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
    // Load app features from server config via /health
    // Returns a promise for proper sequencing on page load
    // Use AbortController for timeout (fetch doesn't have native timeout)
    var controller = new AbortController();
    var timeoutId = setTimeout(function() { 
      controller.abort(); 
      console.error('[FEATURES] /health request timed out after 15s');
    }, 15000); // 15 second timeout for slow connections
    
    var healthUrl = '/health';
    // Prepend URL prefix for subpath deployments
    if (urlPrefix) {
      healthUrl = urlPrefix + '/health';
    }
    
    return fetch(healthUrl, { signal: controller.signal })
      .then(r => {
        clearTimeout(timeoutId);
        if (!r.ok) {
          console.error('[FEATURES] /health returned status', r.status);
          throw new Error('HTTP ' + r.status);
        }
        return r.json();
      })
      .then(data => {
        if (data.features) {
          appFeatures = data.features;
          console.log('[FEATURES] Loaded from server:', appFeatures);
          // Update legend visibility based on show_gateways
          var trafficLightLegend = document.getElementById('trafficLightLegend');
          // Initialize control menu checkboxes immediately
          // show_all_nodes removed - now config-only setting
          if (document.getElementById('showGatewaysInput')) {
            document.getElementById('showGatewaysInput').checked = appFeatures.show_gateways;
          }
          if (document.getElementById('showPositionTrailsInput')) {
            document.getElementById('showPositionTrailsInput').checked = appFeatures.show_position_trails;
          }
          if (document.getElementById('showNauticalMarkersInput')) {
            document.getElementById('showNauticalMarkersInput').checked = appFeatures.show_nautical_markers;
          }
          if (document.getElementById('trailHistoryInput')) {
            document.getElementById('trailHistoryInput').value = appFeatures.trail_history_hours || 168;
          }
          // Update legend visibility based on loaded features
          updateLegendVisibility();
          // Apply the real flags to the map (checkbox alone is not enough)
          applyNauticalOverlay();
        } else {
          console.warn('[FEATURES] No features in /health response');
        }
      })
      .catch(e => {
        clearTimeout(timeoutId);
        console.error('[FEATURES] Failed to load app features:', e.message || e);
        // Don't throw - let app continue with defaults
      });
  }

  // Update legend visibility based on current feature settings
  function updateLegendVisibility() {
    // Hide/show movement rings based on position trails setting
    var movementRings = document.getElementById('legendMovementRings');
    if (movementRings) {
      movementRings.style.display = appFeatures.show_position_trails ? 'block' : 'none';
    }

    // Hide/show gateway connections based on show_gateways setting
    var gatewayLegend = document.getElementById('legendGatewayConnections');
    if (gatewayLegend) {
      gatewayLegend.style.display = appFeatures.show_gateways ? 'block' : 'none';
    }
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
        loadAlertStatus();  // fetched on open, not at page load
      }
    }
  };


  // -------------------------------------------------------------------
  // v2.1 bottom sheet: draggable with snap points (collapsed / half / tall)
  // -------------------------------------------------------------------
  var sheetIndex = 0;

  function sheetHeights() {
    var vh = window.innerHeight;
    return [180, Math.round(vh * 0.45), Math.round(vh * 0.70)];
  }

  function setSheet(idx) {
    var sidebar = document.getElementById('sidebar');
    if (!sidebar) return;
    sheetIndex = Math.max(0, Math.min(2, idx));
    sidebar.classList.remove('dragging');
    if (window.innerWidth <= 768) {
      sidebar.style.height = sheetHeights()[sheetIndex] + 'px';
    } else {
      sidebar.style.height = '';
    }
    sidebar.classList.toggle('expanded', sheetIndex > 0);
  }
  window.__setSheet = setSheet;

  // Tap on the handle still cycles: collapsed <-> tall
  window.toggleSheet = function(){
    setSheet(sheetIndex === 0 ? 2 : 0);
  };
  window.toggleSidebar = window.toggleSheet;  // legacy name still used by stubs

  (function initSheetDrag() {
    var handle = document.getElementById('sheet-handle');
    var sidebar = document.getElementById('sidebar');
    if (!handle || !sidebar) return;
    var active = false, moved = false;
    var startY = 0, startH = 0, startIdx = 0, lastY = 0, lastT = 0, vel = 0;

    function pointY(e) { return e.touches ? e.touches[0].clientY : e.clientY; }

    function onDown(e) {
      if (window.innerWidth > 768) return;
      active = true; moved = false;
      startY = lastY = pointY(e);
      startH = sidebar.getBoundingClientRect().height;
      startIdx = sheetIndex;
      lastT = Date.now(); vel = 0;
      sidebar.classList.add('dragging');
      e.preventDefault();
    }

    function onMove(e) {
      if (!active) return;
      var y = pointY(e);
      var now = Date.now();
      if (now > lastT) { vel = (y - lastY) / (now - lastT); }
      lastY = y; lastT = now;
      var delta = startY - y;
      if (Math.abs(delta) > 4) moved = true;
      var h = Math.max(120, Math.min(window.innerHeight * 0.75, startH + delta));
      sidebar.style.height = h + 'px';
      e.preventDefault();
    }

    function onUp() {
      if (!active) return;
      active = false;
      if (!moved) { window.toggleSheet(); return; }  // it was a tap
      var hs = sheetHeights();
      var h = sidebar.getBoundingClientRect().height;
      var idx = 0, best = 1e9;
      for (var i = 0; i < hs.length; i++) {
        var d = Math.abs(hs[i] - h);
        if (d < best) { best = d; idx = i; }
      }
      // A flick (fast release) moves at least one level in its direction
      if (vel < -0.5) idx = Math.max(idx, Math.min(2, startIdx + 1));
      else if (vel > 0.5) idx = Math.min(idx, Math.max(0, startIdx - 1));
      setSheet(idx);
    }

    handle.addEventListener('touchstart', onDown, { passive: false });
    handle.addEventListener('pointerdown', onDown);
    document.addEventListener('touchmove', onMove, { passive: false });
    document.addEventListener('pointermove', onMove);
    document.addEventListener('touchend', onUp);
    document.addEventListener('pointerup', onUp);
    window.addEventListener('resize', function(){ setSheet(sheetIndex); });
  })();

  // Attach event listeners to traffic light dots for JavaScript-based tooltips
  function createTooltipElements() {
    // Creates tooltip DOM elements without adding event listeners
    // Event listeners are handled via delegation (see setupTooltipDelegation below)
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
    });
  }

  // Event delegation for tooltips - set up ONCE on app initialization
  // This eliminates the memory leak from repeated addEventListener calls
  function setupTooltipDelegation() {
    var nodesContainer = document.getElementById('nodes');
    if (!nodesContainer) return;

    // Use event capturing (true parameter) to catch events before they bubble
    nodesContainer.addEventListener('mouseenter', function(e) {
      if (e.target.classList.contains('traffic-light-dot')) {
        var tooltip = e.target.querySelector('.js-tooltip');
        if (tooltip) tooltip.style.display = 'block';
      }
    }, true);

    nodesContainer.addEventListener('mouseleave', function(e) {
      if (e.target.classList.contains('traffic-light-dot')) {
        var tooltip = e.target.querySelector('.js-tooltip');
        if (tooltip) tooltip.style.display = 'none';
      }
    }, true);
  }

  // Close sidebar when tapping outside on mobile
  document.addEventListener('touchstart', function(e) {
    if (window.innerWidth <= 768) {  // Only on mobile
      var sidebar = document.getElementById('sidebar');
      var overlay = document.getElementById('sidebar-overlay');
      if (sidebar && sidebar.classList.contains('expanded')) {
        // If touch is outside sidebar and not on FAB/menu buttons, close sidebar
        if (!sidebar.contains(e.target) &&
            e.target.id !== 'menu-fab' &&
            e.target.id !== 'menu-btn' &&
            !e.target.closest('#menu-fab') &&
            !e.target.closest('#menu-btn')) {
          window.__setSheet ? window.__setSheet(0) : sidebar.classList.remove('expanded');
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
    window.map = map;  // Expose to console for debugging
    
    // Define base layers for map
    var osmLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '',
      opacity: 0.5
    });
    
    // OpenSeaMap overlay - nautical markers and depth contours (worldwide)
    window.seamarkOverlay = L.tileLayer('https://tiles.openseamap.org/seamark/{z}/{x}/{y}.png', {
      attribution: '',
      maxZoom: 19,
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


  // Apply the nautical-markers feature flag to the map layer. Used on
  // toggle AND after /health delivers the real flags — previously only the
  // checkbox was updated at load, so the chart could disagree until toggled.
  function applyNauticalOverlay() {
    if (!(window.seamarkOverlay && window.map)) return;
    var map = window.map, overlay = window.seamarkOverlay;
    var hasLayer = map.hasLayer(overlay);
    if (appFeatures.show_nautical_markers) {
      if (!hasLayer) { overlay.addTo(map); }
      else { overlay.redraw(); }  // refetch tiles in case the first load failed
    } else if (hasLayer) {
      map.removeLayer(overlay);
    }
  }

  function getMoveThreshold(){
    var d = document.body && document.body.dataset ? document.body.dataset : {};
    var v = d.moveThreshold || d.moveThresholdMeters || '50';
    var n = parseInt(v, 10);
    if (isNaN(n) || n <= 0) n = 50;
    return n;
  }


  function buildSignalHistogramSVG(historyPoints) {
    // Battery-voltage line chart (RSSI/SNR removed in v2.0).
    // historyPoints: [{ts, voltage, battery_pct}] from the server.
    if (!historyPoints || historyPoints.length === 0) {
      return '<div style="padding:10px;color:var(--ink-2);text-align:center;">No battery history yet</div>';
    }
    var byMinute = {};
    for (var i = 0; i < historyPoints.length; i++) {
      var p = historyPoints[i];
      if (p.voltage == null) continue;
      var key = Math.floor(p.ts / 60);
      if (!byMinute[key]) {
        byMinute[key] = { ts: p.ts, voltage: p.voltage, battery_pct: p.battery_pct, count: 1 };
      } else {
        byMinute[key].count++;
        if (p.ts >= byMinute[key].ts) {
          byMinute[key].ts = p.ts;
          byMinute[key].voltage = p.voltage;
          byMinute[key].battery_pct = p.battery_pct;
        }
      }
    }
    var plotData = Object.keys(byMinute).map(function(k){ return byMinute[k]; }).sort(function(a, b){ return a.ts - b.ts; });
    if (!plotData.length) {
      return '<div style="padding:10px;color:var(--ink-2);text-align:center;">No battery history yet</div>';
    }
    var width = Math.min(window.innerWidth * 0.85, 300), height = 110, padding = 24;
    var plotWidth = width - padding * 2, plotHeight = height - padding * 2;
    var minTime = plotData[0].ts;
    var timeSpan = Math.max(1, plotData[plotData.length - 1].ts - minTime);
    var scaleX = function(ts){ return padding + ((ts - minTime) / timeSpan) * plotWidth; };
    var scaleY = function(v){
      var n = Math.max(0, Math.min(1, (v - 2.8) / (4.3 - 2.8)));
      return padding + plotHeight - n * plotHeight;
    };
    var svg = '<svg width="' + width + '" height="' + height + '" viewBox="0 0 ' + width + ' ' + height + '" style="max-width:100%;height:auto;display:block;font-family:ui-monospace,monospace;font-size:10px;">';
    svg += '<rect width="' + width + '" height="' + height + '" fill="var(--panel-2)" rx="6"/>';
    var marks = [4.2, 3.8, 3.4, 3.0];
    for (var g = 0; g < marks.length; g++) {
      var gy = scaleY(marks[g]);
      svg += '<line x1="' + padding + '" y1="' + gy + '" x2="' + (width - padding) + '" y2="' + gy + '" stroke="var(--line)" stroke-width="1"/>';
      svg += '<text x="2" y="' + (gy + 3) + '" fill="var(--ink-2)">' + marks[g].toFixed(1) + '</text>';
    }
    var path = '';
    for (var j = 0; j < plotData.length; j++) {
      path += (j === 0 ? 'M' : 'L') + scaleX(plotData[j].ts) + ',' + scaleY(plotData[j].voltage) + ' ';
    }
    svg += '<path d="' + path + '" stroke="var(--good)" stroke-width="2" fill="none"/>';
    for (var k = 0; k < plotData.length; k++) {
      var q = plotData[k];
      var x = scaleX(q.ts), y = scaleY(q.voltage);
      var tip = 'Battery: ' + (formatBattery(q.voltage, q.battery_pct) || '?');
      if (q.count > 1) tip += '\n(' + q.count + ' samples)';
      tip += '\n' + new Date(q.ts * 1000).toLocaleString();
      var tipAttr = tip.replace(/"/g, '&quot;');
      svg += '<rect x="' + (x - 8) + '" y="' + (padding - 5) + '" width="16" height="' + (plotHeight + 10) + '" fill="transparent" style="cursor:pointer;" class="histogram-hover" data-tooltip="' + tipAttr + '"/>';
      svg += '<circle cx="' + x + '" cy="' + y + '" r="3" fill="var(--good)" opacity="0.85" style="cursor:pointer;" class="histogram-point" data-tooltip="' + tipAttr + '"/>';
    }
    svg += '<text x="' + padding + '" y="' + (height - 4) + '" fill="var(--good)" font-weight="bold">● Battery voltage</text>';
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

  // ---- v2.0 card: headline state word + labeled chips ----
  function nodeAttentionRank(node) {
    // Lower rank sorts first: alarm situations surface without scrolling.
    // Off location beats everything; battery alarms outrank routine states
    // (and apply even to movement-muted buoys — mute only covers movement).
    if (!node.is_special) return 7;
    var batt = getBatteryColor(
      node.battery_pct != null ? node.battery_pct : null,
      node.voltage != null ? node.voltage : null
    );
    if (node.moved_far && !node.movement_alerts_muted) return 0;  // off location
    if (batt === 'red') return 1;                                 // critical battery
    var quiet = (node.last_seen && node.last_seen > 0) ? (Date.now() / 1000 - node.last_seen) : null;
    if (node.stale || (quiet != null && quiet > solOrangeThreshold)) return 2;  // gone quiet
    if (batt === 'yellow') return 3;                              // weak battery
    if (!(node.last_position_update > 0)) return 4;               // no GPS yet
    if (node.movement_alerts_muted) return 6;                     // parked/muted
    return 5;                                                     // all well
  }

  function nodeHeadlineState(node) {
    var d = node.distance_from_origin_m;
    var dist = (d == null || isNaN(d)) ? '' : Math.round(d) + ' m from home';
    if (node.is_special) {
      if (node.movement_alerts_muted) return { cls: 'muted-s', word: 'Muted 🔕', detail: dist };
      if (node.moved_far) return { cls: 'moved', word: 'Moved', detail: dist };
      if (!node.last_seen || node.last_seen <= 0) {
        return { cls: 'nofix', word: 'Waiting for data', detail: '' };
      }
      var hasRealFix = node.last_position_update != null && node.last_position_update > 0;
      if (!hasRealFix) return { cls: 'nofix', word: 'No GPS yet', detail: 'heard ' + formatTimeAgo(node.last_seen) };
      var quietFor = (Date.now() / 1000 - node.last_seen);
      if (node.stale || (quietFor != null && quietFor > solOrangeThreshold)) {
        return { cls: 'stale', word: 'Stale', detail: 'quiet ' + formatTimeAgo(node.last_seen) };
      }
      return { cls: 'ok', word: 'On station', detail: dist };
    }
    if (node.stale || node.status === 'red') return { cls: 'stale', word: 'Stale', detail: 'heard ' + formatTimeAgo(node.last_seen) };
    return { cls: 'ok', word: 'Relaying', detail: 'heard ' + formatTimeAgo(node.last_seen) };
  }

  function chipHtml(label, value, color, fill) {
    var led = color === 'green' ? 'g' : color === 'yellow' ? 'y' : color === 'red' ? 'r' : 'n';
    var cls = 'chip chip-' + label.toLowerCase();
    if (fill && color === 'yellow') cls += ' chip-fill-y';
    else if (fill && color === 'red') cls += ' chip-fill-r';
    else if (color === 'red') cls += ' alert-led';
    return '<span class="' + cls + '">' +
           '<span class="led ' + led + '"></span>' +
           '<span class="lbl">' + label + '</span><b>' + value + '</b></span>';
  }

  // Cached /api/special/history/batch response, refreshed with the trails poll
  var sparklineHistory = {};

  function buildBatterySparkline(nodeId) {
    // Tiny inline voltage trend on the card; tap the card's history button
    // for the full chart. Uses data already fetched for the trails — no
    // extra requests.
    var data = sparklineHistory[String(nodeId)];
    var pts = (data && data.points) ? data.points.filter(function(p){ return p.voltage != null; }) : [];
    if (pts.length < 2) return '';
    var w = 84, h = 20, pad = 2;
    var t0 = pts[0].ts, span = Math.max(1, pts[pts.length - 1].ts - t0);
    var line = '';
    for (var i = 0; i < pts.length; i++) {
      var x = pad + ((pts[i].ts - t0) / span) * (w - 2 * pad);
      var n = Math.max(0, Math.min(1, (pts[i].voltage - 2.8) / (4.3 - 2.8)));
      var y = (h - pad) - n * (h - 2 * pad);
      line += (i === 0 ? 'M' : 'L') + x.toFixed(1) + ',' + y.toFixed(1) + ' ';
    }
    var last = pts[pts.length - 1];
    var lx = pad + ((last.ts - t0) / span) * (w - 2 * pad);
    var ln = Math.max(0, Math.min(1, (last.voltage - 2.8) / (4.3 - 2.8)));
    var ly = (h - pad) - ln * (h - 2 * pad);
    return '<svg class="sparkline" width="' + w + '" height="' + h + '" viewBox="0 0 ' + w + ' ' + h + '" aria-hidden="true">' +
           '<path d="' + line + '" fill="none" stroke="var(--good)" stroke-width="1.5" opacity="0.85"/>' +
           '<circle cx="' + lx.toFixed(1) + '" cy="' + ly.toFixed(1) + '" r="2" fill="var(--good)"/>' +
           '</svg>';
  }

  function buildNodeCard(node){
    var clickable = (node.lat != null && node.lon != null) || (node.is_special && node.origin_lat != null && node.origin_lon != null);

    var displayName = node.name;
    if (!displayName || displayName === 'Unknown') {
      displayName = (node.is_special && node.special_label) ? node.special_label : String(node.id);
    }

    var muteBadge = (node.is_special && node.movement_alerts_muted)
      ? '<span class="mutebadge" title="Movement alerts muted">🔕</span>' : '';

    var bat = node.battery_pct != null ? node.battery_pct : null;
    var voltage = node.voltage != null ? node.voltage : null;
    var battColor = getBatteryColor(bat, voltage);
    var battCls = battColor === 'green' ? 'batt-g' : battColor === 'yellow' ? 'batt-y' : battColor === 'red' ? 'batt-r' : 'batt-n';

    var actionBtn = '';
    if (node.is_special) {
      actionBtn = '<button class="iconbtn ' + battCls + '" onclick="event.stopPropagation();showNodeDetails(' + node.id + ',\'' + displayName.replace(/'/g, "\\'") + '\')" title="Battery history">▁▃▅</button>';
    } else if (node.is_gateway) {
      actionBtn = '<button class="iconbtn" onclick="event.stopPropagation();showGatewayDetails(' + node.id + ',\'' + displayName.replace(/'/g, "\\'") + '\')" title="Gateway details">ℹ️</button>';
    }

    var header = '<div class="toprow">' +
                 '<div class="node-name">' + escapeHtml(displayName) + '</div>' +
                 muteBadge + actionBtn + '</div>';

    var st = nodeHeadlineState(node);
    var statePill = '<div><span class="state ' + st.cls + '">' + st.word +
                    (st.detail ? ' <small>· ' + st.detail + '</small>' : '') + '</span></div>';

    var chips = '';
    if (node.is_special) {
      var lpu = getAgeStatus(node.last_position_update, lpuBlueThreshold, lpuOrangeThreshold);
      var sol = getAgeStatus(node.last_seen, solBlueThreshold, solOrangeThreshold);
      var batteryStr = formatBattery(voltage, bat) || '?';
      // Anchoring quality: spread of the last week's fixes around their
      // centroid — shown next to distance-to-home while we evaluate it.
      var spreadChip = (node.anchor_spread_m != null)
        ? chipHtml('Swing', 'σ ' + Math.round(node.anchor_spread_m) + ' m', null)
        : '';
      chips = '<div class="chips">' +
              chipHtml('Fix', lpu.text, lpu.color) +
              chipHtml('Heard', sol.text, sol.color) +
              chipHtml('Batt', batteryStr, battColor, true) +
              spreadChip +
              buildBatterySparkline(node.id) +
              '</div>';
    }

    var classes = 'node ' + node.status + (node.is_special ? ' special' : '') + (node.is_gateway && !node.is_special ? ' gateway-node' : '');
    if (node.is_special && node.moved_far) classes += ' moved-alert';
    if (node.stale && !node.is_special) classes += ' gray';

    var clickAttr = '';
    if (clickable) {
      var clickLat = node.lat != null ? node.lat : node.origin_lat;
      var clickLon = node.lon != null ? node.lon : node.origin_lon;
      if (clickLat != null && clickLon != null) {
        clickAttr = ' onclick="centerNode(' + parseFloat(clickLat) + ',' + parseFloat(clickLon) + ')"';
      }
    }
    return '<div class="' + classes + '"' + clickAttr + '>' + header + statePill + chips + '</div>';
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
        
        // Store all nodes for access in popup building
        currentNodesData = data.nodes;
        
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

            // Backend only sends special nodes + gateways
            // Frontend filter: user can hide gateways in real-time
            if (!appFeatures.show_gateways) {
              var tmp = [];
              for (var m = 0; m < list.length; m++) {
                if (list[m].is_special) {
                  tmp.push(list[m]);
                }
              }
              list = tmp;
            }

            // Sort: special nodes first (alphabetically), then gateways (alphabetically)
            var special = [], gateway = [];
            for (var i = 0; i < list.length; i++) {
              if (list[i].is_special) special.push(list[i]);
              else if (list[i].is_gateway) gateway.push(list[i]);
            }
            special.sort(function(a, b) {
              // Attention first: Moved / Stale bubble to the top of the list
              var ra = nodeAttentionRank(a), rb = nodeAttentionRank(b);
              if (ra !== rb) return ra - rb;
              var nameA = (a.name || a.special_label || '').toLowerCase();
              var nameB = (b.name || b.special_label || '').toLowerCase();
              return nameA < nameB ? -1 : nameA > nameB ? 1 : 0;
            });
            gateway.sort(function(a, b) {
              var nameA = (a.name || '').toLowerCase();
              var nameB = (b.name || '').toLowerCase();
              if (nameA < nameB) return -1;
              if (nameA > nameB) return 1;
              return 0;
            });
            list = special.concat(gateway);
            // Keep latest special-node snapshot for the Controls-tab mute list
            lastSpecialNodes = special;
            renderMuteList();
            // Clear existing nodes and update with DocumentFragment (eliminates layout thrashing)
            var nodesContainer = document.getElementById('nodes');
            var fragment = document.createDocumentFragment();

            // Build all cards in DocumentFragment (off-DOM, no reflows)
            for(var q=0;q<list.length;q++){
              var cardElement = buildNodeCardElement(list[q]);
              fragment.appendChild(cardElement);
            }

            // Single DOM update - only 1 reflow instead of N reflows
            nodesContainer.textContent = ''; // Faster than innerHTML = ''
            nodesContainer.appendChild(fragment);
            document.getElementById('node-count').textContent = String(list.length);

            // Create tooltip DOM elements (event delegation handles interactions)
            setTimeout(createTooltipElements, 0);
          
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
            
            // Collect all gateway IDs that are being rendered as part of gateway_connections
            // so we don't render them again as regular nodes when show_all_nodes is enabled
            var renderedGatewayIds = {};
            for (var i = 0; i < toMap.length; i++) {
              var checkNode = toMap[i];
              if (checkNode.is_special && checkNode.gateway_connections && appFeatures.show_gateways) {
                for (var gc_check = 0; gc_check < checkNode.gateway_connections.length; gc_check++) {
                  renderedGatewayIds[checkNode.gateway_connections[gc_check].id] = true;
                }
              }
            }
            
            for(var r=0; r<toMap.length; r++){
              var node = toMap[r];
              var key = String(node.id);
              var color = '#f44336';

              // Skip gateways already shown as gateway_connections (avoid double-rendering)
              if (node.is_gateway && renderedGatewayIds[node.id]) {
                continue;
              }

              // Color coding: Special nodes (yellow/gray) or Gateways (green)
              if (node.is_special) {
                // Special nodes: yellow when online, gray when offline
                if (node.status === 'gray' || node.status === 'red') {
                  color = '#999999';  // Gray for offline special nodes
                } else if (node.stale) {
                  color = '#888888';
                } else {
                  color = '#FFD700';  // Yellow for online special nodes
                }
              } else if (node.is_gateway) {
                // Gateways: always green
                color = '#4CAF50';
              }
              
              // Build popup using helper function
              var displayInfo = {
                name: node.name || 'Unknown',
                label: (node.is_special && node.special_label) ? ' (' + node.special_label + ')' : '',
                stale: node.stale ? ' <em>(stale)</em>' : '',
                noFix: (node.status === 'gray') ? ' <em>(awaiting GPS)</em>' : '',
                short: node.short || '?',
                channel: node.channel_name ? node.channel_name : (node.modem_preset ? node.modem_preset : '')
              };
              var popup = buildMapPopup(node, displayInfo);

              
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
                var tooltipText = escapeHtml(node.name || 'Unknown');
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

                // Draw lines to all first-hop gateways
                if (appFeatures.show_gateways && node.is_special && node.lat != null && node.lon != null && node.gateway_connections && node.gateway_connections.length > 0) {
                  var activeGatewayKeys = [];

                  // Loop through all gateway connections
                  for (var gwIdx = 0; gwIdx < node.gateway_connections.length; gwIdx++) {
                    var gw = node.gateway_connections[gwIdx];

                    // Only show if gateway has position data
                    if (gw.lat != null && gw.lon != null) {
                      var lineKey = 'gw_' + node.id + '_' + gw.id;
                      activeGatewayKeys.push(lineKey);

                      var lineOpts = {
                        color: '#FF6F00',  // Orange for all gateways
                        weight: 3,
                        opacity: 0.9,
                        dashArray: '3, 5',
                        lineCap: 'round',
                        lineJoin: 'round',
                        interactive: true,
                        bubblingMouseEvents: false
                      };
                      var latlngs = [[node.lat, node.lon], [gw.lat, gw.lon]];

                      if (!gatewayLines[lineKey]) {
                        gatewayLines[lineKey] = L.polyline(latlngs, lineOpts).addTo(map);
                      } else {
                        gatewayLines[lineKey].setLatLngs(latlngs);
                        gatewayLines[lineKey].setStyle(lineOpts);
                      }

                      // Update popup with gateway info
                      var popup = 'Gateway: ' + escapeHtml(gw.name);
                      gatewayLines[lineKey].bindPopup(popup);

                      // Hover effects
                      gatewayLines[lineKey].on('mouseover', function() {
                        this.setStyle({ weight: 5, opacity: 1.0 });
                      });
                      gatewayLines[lineKey].on('mouseout', function() {
                        this.setStyle({ weight: 3, opacity: 0.9 });
                      });

                      // Create gateway marker
                      var gwMarkerKey = 'gw_' + node.id + '_' + gw.id;
                      var reliabilityScore = gw.reliability_score !== undefined ? gw.reliability_score : 50;
                      var circleRadius = 5 + ((reliabilityScore - 50) / 50) * 4;  // 5-9 px range
                      var fillColor = gw.confidence_level === 'direct' ? '#2196F3' : '#4CAF50';

                      if (!gatewayMarkers[gwMarkerKey]) {
                        gatewayMarkers[gwMarkerKey] = L.circleMarker([gw.lat, gw.lon], {
                          radius: circleRadius,
                          fillColor: fillColor,
                          color: fillColor === '#2196F3' ? '#0D47A1' : '#2E7D32',
                          weight: 2,
                          opacity: 0.8,
                          fillOpacity: 0.7
                        }).addTo(map);
                      } else {
                        gatewayMarkers[gwMarkerKey].setLatLng([gw.lat, gw.lon]);
                        gatewayMarkers[gwMarkerKey].setRadius(circleRadius);
                        gatewayMarkers[gwMarkerKey].setStyle({
                          fillColor: fillColor,
                          color: fillColor === '#2196F3' ? '#0D47A1' : '#2E7D32'
                        });
                      }
                      // Clicking the marker opens the same gateway details view
                      // as the card — one place for all gateway info.
                      (function(gwId, gwName) {
                        gatewayMarkers[gwMarkerKey].off('click').on('click', function() {
                          showGatewayDetails(gwId, gwName);
                        });
                      })(gw.id, gw.name);
                    }
                  }

                  // Clean up old gateway lines/markers for this node that are no longer active
                  for (var lineKey2 in gatewayLines) {
                    if (lineKey2.indexOf('gw_' + node.id + '_') === 0 && activeGatewayKeys.indexOf(lineKey2) === -1) {
                      map.removeLayer(gatewayLines[lineKey2]);
                      delete gatewayLines[lineKey2];
                    }
                  }
                  for (var markerKey2 in gatewayMarkers) {
                    if (markerKey2.indexOf('gw_' + node.id + '_') === 0 && activeGatewayKeys.indexOf(markerKey2.replace('gw_', 'gw_')) === -1) {
                      map.removeLayer(gatewayMarkers[markerKey2]);
                      delete gatewayMarkers[markerKey2];
                    }
                  }
                } else if (!appFeatures.show_gateways || !node.gateway_connections || node.gateway_connections.length === 0) {
                  // Remove gateway lines and markers for this node if feature disabled or no gateways
                  for (var lineKey in gatewayLines) {
                    if (lineKey.indexOf('gw_' + node.id + '_') === 0) {
                      map.removeLayer(gatewayLines[lineKey]);
                      delete gatewayLines[lineKey];
                    }
                  }
                  for (var markerKey in gatewayMarkers) {
                    if (markerKey.indexOf('gw_' + node.id + '_') === 0) {
                      map.removeLayer(gatewayMarkers[markerKey]);
                      delete gatewayMarkers[markerKey];
                    }
                  }
                }
              }
            }
            
            if (appFeatures.show_position_trails){
              // Batch API call: get trail history for ALL special nodes in one request
              // Eliminates N+1 query problem (was making 1 request per special node)
              var hours = parseInt(appFeatures.trail_history_hours || '24', 10);
              makeApiRequest('GET', 'api/special/history/batch?hours=' + hours, function(xhr2){
                if (xhr2.status === 200){
                  try {
                    var batchData = JSON.parse(xhr2.responseText);
                    var trails_data = batchData.trails || {};
                    // Cache per-node history so buoy cards can draw battery sparklines
                    sparklineHistory = trails_data;

                    // Process trail history for each special node
                    for(var t=0; t<toMap.length; t++){
                      var node = toMap[t];
                      if(!node.is_special) continue;

                      var nodeTrailData = trails_data[String(node.id)];
                      if (!nodeTrailData) continue;

                      // Battery-only telemetry points (no GPS fix yet) can be mixed
                      // in; the trail itself only ever plots points with a position.
                      var pts = (nodeTrailData.points || []).filter(function(p){
                        return p.lat != null && p.lon != null;
                      });

                      // Remove old trail polyline
                        if (trails[node.id]) { 
                          map.removeLayer(trails[node.id]); 
                          delete trails[node.id]; 
                        }
                        
                        // Remove old position history markers
                        if (trail_markers[node.id]) {
                          for (var m = 0; m < trail_markers[node.id].length; m++) {
                            map.removeLayer(trail_markers[node.id][m]);
                          }
                          delete trail_markers[node.id];
                        }
                        
                        if (pts.length >= 2){
                          var latlngs = [];
                          trail_markers[node.id] = [];

                          // Create markers for each trail point
                          for(var u=0; u<pts.length; u++){
                            var pnt = pts[u];
                            latlngs.push([pnt.lat, pnt.lon]);

                            // Get marker style based on position (first/last/middle)
                            var markerOpts = getTrailMarkerStyle(u, pts.length);

                            // Create marker
                            var historyMarker = L.circleMarker([pnt.lat, pnt.lon], markerOpts).addTo(map);

                            // Build and bind popup
                            var popupText = buildTrailPopup(pnt, u, pts.length, node);
                            historyMarker.bindPopup(popupText);

                            trail_markers[node.id].push(historyMarker);
                          }

                          // Draw trail polyline (light blue line)
                          trails[node.id] = L.polyline(latlngs, {
                            color: '#64B5F6',
                            weight: 3,
                            opacity: 0.7
                          }).addTo(map);
                        }
                        // Trail data empty for this node
                    }
                  } catch(e){
                    console.warn('Error parsing batch trail history', e);
                  }
                } else {
                  console.warn('Batch trail API request failed:', xhr2.status);
                }
              });
            } else { 
              // Remove trails and history markers
              for (var tk in trails){ 
                if(trails.hasOwnProperty(tk)){ 
                  map.removeLayer(trails[tk]); 
                  delete trails[tk]; 
                }
              }
              for (var tmk in trail_markers) {
                if (trail_markers.hasOwnProperty(tmk)) {
                  for (var tm = 0; tm < trail_markers[tmk].length; tm++) {
                    map.removeLayer(trail_markers[tmk][tm]);
                  }
                  delete trail_markers[tmk];
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
      if (!statusEl) {
        console.warn('[STATUS] Status element not found in DOM');
        return;
      }
      console.log('[STATUS] Fetching health status...');
      
      makeApiRequest('GET', 'health', function(xhr){ 
        try {
          if (xhr.status === 200){ 
            // Connection restored
            window.connectionLost = false;
              hideConnectionBanner();
            var data2 = JSON.parse(xhr.responseText); 
            var txt = 'disconnected', pulse = 'down';
            if (data2 && data2.mqtt_status === 'receiving_packets') { txt = 'mesh live'; pulse = ''; }
            else if (data2 && data2.mqtt_status === 'stale_data') { txt = 'no recent packets'; pulse = 'warn'; }
            else if (data2 && data2.mqtt_status === 'connected_to_server') { txt = 'connected'; pulse = ''; }
            else if (data2 && data2.mqtt_status === 'connecting') { txt = 'connecting…'; pulse = 'warn'; }
            statusEl.textContent = txt;
            var pulseEl = document.getElementById('mqtt-pulse');
            if (pulseEl) pulseEl.className = 'pulse' + (pulse ? ' ' + pulse : '');

            var uptimeEl = document.getElementById('server-uptime');
            if (uptimeEl && data2 && data2.server_start_ts) {
              uptimeEl.textContent = 'up ' + formatTimeAgo(data2.server_start_ts);
            }
          } else if (xhr.status === 429) {
            pausePollingForRateLimit();
            statusEl.textContent = '⏸️ Rate limited (paused 60s)';
            console.warn('[STATUS] Rate limited (429)');
          } else if (xhr.status === 0) {
            // Network error - server unreachable
            window.connectionLost = true;
              showConnectionBanner();
            statusEl.textContent = '❌ Server Unreachable';
            console.warn('[STATUS] Server unreachable (status 0 - network error)');
          } else if (xhr.status === 401) {
            statusEl.textContent = '🔒 Unauthorized';
            console.warn('[STATUS] Unauthorized (401)');
          } else {
            console.warn('[STATUS] Unexpected response status:', xhr.status, '- Response:', xhr.responseText ? xhr.responseText.substring(0, 100) : '(no response)');
            statusEl.textContent = '❓ Error (' + xhr.status + ')';
          }
        } catch(e) {
          console.error('[STATUS] Error parsing response:', e);
          statusEl.textContent = '❓ Parse error';
        }
      }, null); // No explicit timeout param - uses hardcoded 15s
    } catch(e) {
      // Silent - don't let updateStatus errors break the poll loop
      console.error('[STATUS] Error calling updateStatus:', e);
    }
  }

  window.centerNode = function(lat, lon){ 
    if (map) map.setView([lat, lon], 13);
    // On mobile, close sidebar when clicking a node to show the map
    if (window.innerWidth <= 768) {
      var sidebar = document.getElementById('sidebar');
      if (sidebar && sidebar.classList.contains('expanded')) {
        window.__setSheet ? window.__setSheet(0) : sidebar.classList.remove('expanded');
        var overlay = document.getElementById('sidebar-overlay');
        if (overlay) overlay.style.display = 'none';
      }
    }
  };


  // initChannels removed: channel filter no longer used
  initMap(); 
  
  // Load app features and then fetch initial data
  console.log('[INIT] Starting app initialization...');
  var initComplete = false;
  
  loadAppFeatures().then(function() {
    console.log('[INIT] App features loaded, updating status...');
    updateStatus(); // Call immediately to get initial status
    initComplete = true;
    
    // Initial fetch on page load
    try {
      updateNodes();
    } catch(e) {
      console.error('[INIT] Error in updateNodes:', e);
    }
  }).catch(function(e) {
    console.error('[INIT] Failed to initialize features:', e);
    initComplete = true;
    // Even if features fail to load, try to update status
    setTimeout(function() {
      console.log('[INIT] Retrying status update after feature load failure...');
      updateStatus();
    }, 500);
  });
  
  // Safety fallback: if initialization takes more than 12 seconds, force a status update
  setTimeout(function() {
    if (!initComplete) {
      console.warn('[INIT] Initialization timeout - forcing status update');
      updateStatus();
    }
  }, 12000);
  
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
          progressBar.style.background = 'var(--muted-state)';
          progressBar.style.boxShadow = 'none';
          showConnectionBanner();
        } else if (isRateLimitPaused()) {
          // Red when rate limited
          progressBar.style.background = 'var(--crit)';
        } else {
          // Normal: clear inline overrides so the stylesheet owns the color
          // (green via var(--good); a v1 leftover hard-coded white here and
          // silently overrode any CSS, 100 times a second)
          progressBar.style.background = '';
          progressBar.style.boxShadow = '';
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
  var nodePollInterval = null;
  var pollAttempts = 0;
  var isPageVisible = true;

  // Page Visibility API - pause polling when tab is hidden
  function handleVisibilityChange() {
    if (document.hidden) {
      isPageVisible = false;
      console.log('[POLLING] Page hidden - pausing polls');
    } else {
      isPageVisible = true;
      console.log('[POLLING] Page visible - resuming polls');
      // Immediately poll when page becomes visible again
      try {
        updateStatus();
        updateNodes();
      } catch(e) {
        console.error('[POLLING] Error on visibility resume:', e);
      }
    }
  }

  // Listen for page visibility changes
  if (typeof document.hidden !== 'undefined') {
    document.addEventListener('visibilitychange', handleVisibilityChange);
  }

  function startStatusPolling(){
    try {
      if (statusPollInterval) {
        clearInterval(statusPollInterval);
      }
      pollAttempts = 0;

      statusPollInterval = setInterval(function() {
        try {
          // Skip polling if page is hidden or rate limited
          if (!isPageVisible || isRateLimitPaused()) {
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
    nodePollInterval = setInterval(function(){
      try {
        // Skip polling if page is hidden
        if (!isPageVisible) {
          return;
        }
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
      
      if (isMobile && isLandscape && sidebar && sidebar.classList.contains('expanded')) {
        // Auto-close sidebar in landscape to maximize map view
        window.__setSheet ? window.__setSheet(0) : sidebar.classList.remove('expanded');
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
  window.showGatewayDetails = function(gatewayId, gatewayName) {
    // Display gateway details including which special nodes receive through it
    
    // Find the gateway node in currentNodesData
    var gatewayNode = null;
    if (currentNodesData && currentNodesData.length > 0) {
      for (var i = 0; i < currentNodesData.length; i++) {
        if (currentNodesData[i].id === gatewayId) {
          gatewayNode = currentNodesData[i];
          break;
        }
      }
    } else {
      console.error('currentNodesData is empty or undefined:', currentNodesData);
    }
    
    if (!gatewayNode) {
      console.error('Gateway node not found in currentNodesData');
      alert('Gateway not found (ID: ' + gatewayId + ')');
      return;
    }
    
    // Build the gateway details content
    var details = '';
    
    // Gateway identification
    details += '<strong>Gateway ID:</strong> ' + gatewayId + ' (0x' + gatewayId.toString(16).toUpperCase() + ')<br>';
    if (gatewayNode.name) {
      details += '<strong>Name:</strong> ' + escapeHtml(gatewayNode.name) + '<br>';
    }
    
    // Position if available
    if (gatewayNode.lat !== undefined && gatewayNode.lat !== null && gatewayNode.lon !== undefined && gatewayNode.lon !== null) {
      details += '<strong>Position:</strong> ' + gatewayNode.lat.toFixed(4) + ', ' + gatewayNode.lon.toFixed(4) + '<br>';
    }
    
    // Gateway hardware info if available
    if (gatewayNode.hardware_model) {
      details += '<strong>Hardware:</strong> ' + gatewayNode.hardware_model + '<br>';
    }
    if (gatewayNode.role) {
      details += '<strong>Role:</strong> ' + escapeHtml(gatewayNode.role) + '<br>';
    }
    if (gatewayNode.is_online !== undefined) {
      details += '<strong>Status:</strong> ' + (gatewayNode.is_online ? '<span style="color:green;">🟢 Online</span>' : '<span style="color:red;">🔴 Offline</span>') + '<br>';
    }

    // Reliability summary (was previously only in the map marker popup)
    if (gatewayNode.reliability_score !== undefined) {
      var confLabel = gatewayNode.confidence_level === 'direct' ? '✅ direct reception' :
                      gatewayNode.confidence_level === 'partial' ? '⚠️ partial hop data' : '';
      details += '<strong>Reliability:</strong> ' + gatewayNode.reliability_score + '/100' +
                 ' · ' + (gatewayNode.detection_count || 0) + ' detection' +
                 ((gatewayNode.detection_count || 0) !== 1 ? 's' : '') +
                 (confLabel ? ' · ' + confLabel : '') + '<br>';
    }

    // Receiving from section
    details += '<br><strong style="color:#2196F3;">📶 Receiving from:</strong><br>';
    
    var receivingConnections = [];
    var allSpecialNodes = currentNodesData || [];
    
    // Find all special nodes that receive through this gateway
    for (var snIdx = 0; snIdx < allSpecialNodes.length; snIdx++) {
      var specialNode = allSpecialNodes[snIdx];
      if (specialNode.is_special && specialNode.gateway_connections) {
        for (var gwIdx = 0; gwIdx < specialNode.gateway_connections.length; gwIdx++) {
          var gw = specialNode.gateway_connections[gwIdx];
          if (gw.id === gatewayId) {
            receivingConnections.push({
              nodeName: specialNode.name || ('Node ' + specialNode.id),
              nodeId: specialNode.id,
              rssi: gw.rssi,
              snr: gw.snr,
              hopsTraveled: gw.hop_start - gw.hop_limit,
              hopStart: gw.hop_start,
              hopLimit: gw.hop_limit,
              reliability: gw.reliability_score,
              confidence: gw.confidence
            });
          }
        }
      }
    }
    
    if (receivingConnections.length === 0) {
      details += '<span style="opacity:0.7;">No active connections</span><br>';
    } else {
      // Sort by RSSI (best signal first)
      receivingConnections.sort(function(a, b) {
        return (b.rssi || -150) - (a.rssi || -150);
      });
      
      for (var i = 0; i < receivingConnections.length; i++) {
        var conn = receivingConnections[i];
        var marker = i === 0 ? ' ⭐' : '';
        var hopStr = ' (' + conn.hopsTraveled + ' hop' + (conn.hopsTraveled !== 1 ? 's' : '') + ')';

        
        details += '├─ <strong>' + conn.nodeName + '</strong>' + marker + '<br>';
        details += '│  ' + hopStr;
        details += '<br>';
      }
    }
    
    // Display in modal if available
    var modal = document.getElementById('nodeDetailsModal');
    var title = document.getElementById('modalTitle');
    var container = document.getElementById('histogramContainer');
    
    if (modal && title && container) {
      title.textContent = '📡 ' + gatewayName + ' (Gateway)';
      container.innerHTML = '<div style="padding:12px;font-size:13px;line-height:1.6;">' + details + '</div>';
      modal.style.display = 'flex';
    } else {
      console.warn('Modal elements missing, using fallback alert');
      // Fallback to alert
      alert('Gateway: ' + gatewayName + '\n\n' + details.replace(/<[^>]*>/g, '\n'));
    }
  };

  window.showNodeDetails = function(nodeId, nodeName) {
    var modal = document.getElementById('nodeDetailsModal');
    var title = document.getElementById('modalTitle');
    var container = document.getElementById('histogramContainer');
    
    if (!modal) return;
    
    title.textContent = 'Battery history: ' + nodeName;
    container.innerHTML = '<div style="color:#999;">Loading signal history...</div>';
    modal.style.display = 'flex';
    
    // Fetch signal history from API for other nodes
    var url = '/api/signal/history?node_id=' + nodeId;
    var fetchOptions = {};
    if (apiKeyRequired && apiKey) {
      fetchOptions.headers = {
        'Authorization': 'Bearer ' + apiKey
      };
    }
    
    fetch(url, fetchOptions)
      .then(function(response) {
        if (response.status === 401) {
          // API key required but missing or invalid - prompt user
          if (apiKeyRequired && !isLocalhost) {
            showApiKeyModal();
            throw new Error('Unauthorized - please enter API key');
          }
          throw new Error('Unauthorized');
        }
        return response.json();
      })
      .then(function(data) {
        if (data.points && data.points.length > 0) {
          var node = currentNodesData.find(function(n) { return n.id === nodeId; });

          // Fill missing voltage/battery_pct in points with the node's latest sample
          var displayData = data.points;
          if (node && node.voltage != null) {
            displayData = data.points.map(function(point) {
              return {
                ts: point.ts,
                lat: point.lat,
                lon: point.lon,
                alt: point.alt,
                voltage: point.voltage != null ? point.voltage : node.voltage,
                battery_pct: point.battery_pct != null ? point.battery_pct : node.battery_pct,
                rssi: point.rssi,
                snr: point.snr
              };
            });
          }

          var svg = buildSignalHistogramSVG(displayData);
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


