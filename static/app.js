/* Buoy Tracker Client Script (ES5) */
(function(){
  var APP_JS_VERSION = 'v3';
  
  // Get API configuration from page data attributes
  var apiKeyRequired = document.body.dataset.apiKeyRequired === 'true';
  var isLocalhost = document.body.dataset.isLocalhost === 'true';
  var apiKey = document.body.dataset.apiKey || '';
  
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
    var modal = document.getElementById('api-key-modal');
    if (modal) {
      modal.style.display = 'flex';
      document.getElementById('api-key-input').focus();
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
        // Refresh data with new key
        refreshAllData();
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
  var movedAlertShown = {}; // track one-time alerts per node id
  var specialPackets = {}; // cache of special node packets
  
  // Helper function to make authenticated API requests
  function makeApiRequest(method, url, callback) {
    try {
      var xhr = new XMLHttpRequest();
      xhr.open(method, url, true);
      
      // Add API key header if authentication is required
      if (apiKeyRequired && apiKey) {
        xhr.setRequestHeader('Authorization', 'Bearer ' + apiKey);
      }
      
      // Add cache-busting parameter for GET requests
      if (method === 'GET' && url.indexOf('?') === -1) {
        url += '?_=' + Date.now();
      }
      
      xhr.onreadystatechange = function(){
        if (xhr.readyState === 4){
          // If 401 Unauthorized and we need auth, prompt for key
          // This happens when stored key expires or is invalid
          if (xhr.status === 401 && apiKeyRequired && !isLocalhost) {
            apiKey = ''; // Clear invalid key
            localStorage.removeItem('tracker_api_key'); // Don't try again
            showApiKeyModal();
          }
          // If 429 Too Many Requests (rate limit), pause polling and show message
          if (xhr.status === 429) {
            pausePollingForRateLimit();
            var rateLimitMsg = document.getElementById('rate-limit-message');
            if (!rateLimitMsg) {
              rateLimitMsg = document.createElement('div');
              rateLimitMsg.id = 'rate-limit-message';
              rateLimitMsg.style.cssText = 'position: fixed; top: 10px; right: 10px; background-color: #ff9800; color: white; padding: 10px 15px; border-radius: 4px; font-weight: bold; z-index: 10000; box-shadow: 0 2px 5px rgba(0,0,0,0.3);';
              document.body.appendChild(rateLimitMsg);
            }
            rateLimitMsg.textContent = '⚠️ Rate limit reached - polling paused for 60 seconds';
            // Auto-hide after 5 seconds (but polling stays paused for 60)
            setTimeout(function() { if (rateLimitMsg && rateLimitMsg.parentNode) rateLimitMsg.parentNode.removeChild(rateLimitMsg); }, 5000);
          }
          callback(xhr);
        }
      };
      
      xhr.send();
    } catch(e) {
      console.error('API request error:', e);
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


  var showAllNodesEl = document.getElementById('show-all-nodes');
  // offlineEl removed: always show special nodes, even when offline
  var trailsEl = document.getElementById('toggle-trails');
  var hoursEl = document.getElementById('trail-hours');

    // Ensure the menu checkbox for trails is always checked on load
  if (trailsEl) trailsEl.checked = true;
  
  // Default to NOT showing all nodes (show only nodes with positions)
  if (showAllNodesEl) showAllNodesEl.checked = false;
  if (trailsEl) trailsEl.checked = true;
  function attachChange(el){ if(el && el.addEventListener){ el.addEventListener('change', function(){ updateNodes(); }); } }
  attachChange(showAllNodesEl); attachChange(trailsEl);
  
  // Add validation for trail-hours input
  if (hoursEl) {
    hoursEl.addEventListener('change', function() {
      var val = parseInt(this.value, 10);
      var max = parseInt(this.max, 10);
      var min = parseInt(this.min, 10);
      if (val > max) {
        alert('Trail history maximum is ' + max + ' hours (7 days).\nValue has been adjusted to ' + max + ' hours.');
        this.value = max;
      } else if (val < min) {
        alert('Trail history minimum is ' + min + ' hour.\nValue has been adjusted to ' + min + ' hour.');
        this.value = min;
      }
      updateNodes();
    });
    hoursEl.addEventListener('input', function() {
      var val = parseInt(this.value, 10);
      var max = parseInt(this.max, 10);
      if (!isNaN(val) && val > max) {
        this.style.borderColor = '#f44336';
        this.title = 'Maximum is ' + max + ' hours (7 days)';
      } else {
        this.style.borderColor = '';
        this.title = '';
      }
    });
  }

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
    map = L.map('map').setView([parseFloat(d.defaultLat || '0'), parseFloat(d.defaultLon || '0')], parseInt(d.defaultZoom || '2', 10));
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(map);
  }

  function getMoveThreshold(){
    var d = document.body && document.body.dataset ? document.body.dataset : {};
    var v = d.moveThreshold || d.moveThresholdMeters || '50';
    var n = parseInt(v, 10);
    if (isNaN(n) || n <= 0) n = 50;
    return n;
  }

  function formatPacketInfo(packets){
    if (!packets || packets.length === 0) return '';
    
    // Get last 3 packets to show recent activity
    var recentPackets = packets.slice(-3);
    var lines = [];
    
    for (var i = 0; i < recentPackets.length; i++) {
      var pkt = recentPackets[i];
      var line = '';
      
      // Format timestamp
      var now = Date.now() / 1000;
      var age = Math.round(now - pkt.timestamp);
      var ageStr = '';
      if (age < 60) ageStr = age + 's';
      else if (age < 3600) ageStr = Math.floor(age / 60) + 'm';
      else ageStr = Math.floor(age / 3600) + 'h';
      
      // Format packet type
      var typeStr = pkt.packet_type || 'UNKNOWN';
      typeStr = typeStr.replace('_APP', '').replace('_', ' ');
      
      line = ageStr + ' ago: ' + typeStr;
      
      // Add relevant details based on packet type
      if (pkt.packet_type === 'TELEMETRY_APP' && pkt.battery_level != null) {
        line += ' (Bat:' + pkt.battery_level + '%)';
      } else if (pkt.packet_type === 'POSITION_APP' && pkt.lat != null) {
        line += ' (' + pkt.lat.toFixed(4) + ',' + pkt.lon.toFixed(4) + ')';
      } else if (pkt.packet_type === 'NODEINFO_APP' && pkt.long_name) {
        line += ' (' + pkt.long_name + ')';
      } else if (pkt.packet_type === 'MAP_REPORT_APP' && pkt.modem_preset != null) {
        line += ' (Preset:' + pkt.modem_preset + ')';
      }
      
      lines.push(line);
    }
    
    return lines.join('<br>');
  }





  function buildNodeCard(node){
    var clickable = (node.has_fix && node.lat != null && node.lon != null);
    
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
    
    // Compact header: name only
    var header = '<div class="node-name">' + displayName + '</div>';

    // --- Traffic light indicators ---
    var now = Date.now() / 1000;
    // Battery
    var bat = (node.battery != null) ? node.battery : null;
    var voltage = (node.voltage != null) ? node.voltage : null;
    var batteryColor = 'gray';
    if (bat !== null && voltage !== null) {
      if (bat >= 70 && voltage >= 3.7) batteryColor = 'green';
      else if (bat >= 40 && voltage >= 3.5) batteryColor = 'yellow';
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

    // Build traffic light indicators row in order: LPU, distance, SoL, battery
    var indicators = '<div style="display:flex;gap:8px;margin:4px 0 0 0;">'
      + '<span title="Last Position Update" style="display:flex;align-items:center;gap:3px;"><span style="display:inline-block;width:12px;height:12px;border-radius:50%;background:'
      + (lpuColor==='green'?'#4CAF50':lpuColor==='yellow'?'#FFEB3B':lpuColor==='red'?'#F44336':'#bbb')
      + ';border:1px solid #888;"></span><span style="font-size:0.85em;min-width:36px;">LPU '+lpuStr+'</span></span>'
      + (node.is_special?('<span title="Distance from Home" style="display:flex;align-items:center;gap:3px;"><span style="display:inline-block;width:12px;height:12px;border-radius:50%;background:'
      + (distColor==='green'?'#4CAF50':distColor==='yellow'?'#FFEB3B':distColor==='red'?'#F44336':'#bbb')
      + ';border:1px solid #888;"></span><span style="font-size:0.85em;min-width:36px;">'+distStr+'</span></span>'):'')
      + '<span title="Sign of Life" style="display:flex;align-items:center;gap:3px;"><span style="display:inline-block;width:12px;height:12px;border-radius:50%;background:'
      + (solColor==='green'?'#4CAF50':solColor==='yellow'?'#FFEB3B':solColor==='red'?'#F44336':'#bbb')
      + ';border:1px solid #888;"></span><span style="font-size:0.85em;min-width:36px;">SoL '+solStr+'</span></span>'
      + '<span title="Battery" style="display:flex;align-items:center;gap:3px;"><span style="display:inline-block;width:12px;height:12px;border-radius:50%;background:'
      + (batteryColor==='green'?'#4CAF50':batteryColor==='yellow'?'#FFEB3B':batteryColor==='red'?'#F44336':'#bbb')
      + ';border:1px solid #888;"></span><span style="font-size:0.85em;min-width:36px;">'
      + (voltage!==null?voltage.toFixed(2)+'V':'?') + '</span></span>'
      + '</div>';

    var info = indicators;
    var extraInfo = '';
    
    var classes = 'node ' + node.status + (node.is_special ? ' special' : '');
    // Add moved-alert class if special node has moved beyond threshold
    if (node.is_special && node.moved_far) {
      classes += ' moved-alert';
    }
    var clickAttr = '';
    if (clickable) { clickAttr = ' onclick="centerNode(' + node.lat + ',' + node.lon + ')"'; }
    return '<div class="' + classes + '"' + clickAttr + '>' + header + '<div class="node-info">' + info + '</div>' + extraInfo + '</div>';
  }

  // Stop tooltip items from triggering card click
  document.addEventListener('click', function(e) {
    if (e.target.closest('.tooltip-item')) {
      e.stopPropagation();
    }
  }, true);

  function fetchSpecialPackets(callback){
    try {
      makeApiRequest('GET', 'api/special/packets?limit=10', function(xhr){
        if (xhr.status === 200){
          try {
            var data = JSON.parse(xhr.responseText);
            specialPackets = data.packets || {};
            if (callback) callback();
          } catch(e){ 
            console.warn('Failed to parse special packets', e); 
            if (callback) callback(); // Call callback even on error
          }
        } else {
          console.warn('Special packets request failed:', xhr.status);
          if (callback) callback(); // Call callback even on error
        }
      });
    } catch(e){ 
      console.error('Failed to fetch special packets', e); 
      if (callback) callback(); // Call callback even on error
    }
  }

  function updateNodes(){
    try {
      // Add cache-busting parameter to prevent browser caching
      var cacheBuster = '?_=' + Date.now();
      makeApiRequest('GET', 'api/nodes' + cacheBuster, function(xhr){
        if (xhr.status !== 200){ console.warn('nodes request failed', xhr.status); return; }
        var data; try { data = JSON.parse(xhr.responseText); } catch(e){ console.warn('bad json', e); return; }
        if (!data || !data.nodes || !data.nodes.length){ 
          document.getElementById('nodes').innerHTML=''; 
          document.getElementById('node-count').textContent='0'; 
          return; 
        }
            
            // Channel filter removed: skip discoveredChannels logic
            var list = data.nodes.slice(0);
            
            if (showAllNodesEl && !showAllNodesEl.checked){
              var tmp = [];
              for(var m=0;m<list.length;m++){
                if(list[m].is_special) tmp.push(list[m]);
              }
              list = tmp;
            }
            
            
            // Always sort: special nodes at top (alphabetically), non-special nodes by newest seen
            var special = [], nonSpecial = [];
            for (var i = 0; i < list.length; i++) {
              if (list[i].is_special) special.push(list[i]);
              else nonSpecial.push(list[i]);
            }
            special.sort(function(a, b) {
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
            list = special.concat(nonSpecial);
            var outHtml = '';
            for(var q=0;q<list.length;q++){
              outHtml += buildNodeCard(list[q]);
            }
            document.getElementById('nodes').innerHTML = outHtml;
            document.getElementById('node-count').textContent = String(list.length);
          
          if (map){
            var toMap = []; 
            for(var mIdx=0;mIdx<list.length;mIdx++){ 
              var nod = list[mIdx]; 
              if(nod.lat!=null && nod.lon!=null){ 
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
              
              if (node.is_special) {
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
                  // Add age of position data
                  if (node.last_position_update != null) {
                    var now = Date.now() / 1000;
                    var posAge = Math.round(now - node.last_position_update);
                    var posAgeStr = '';
                    if (posAge < 60) posAgeStr = posAge + 's';
                    else if (posAge < 3600) posAgeStr = Math.floor(posAge / 60) + 'm';
                    else posAgeStr = Math.floor(posAge / 3600) + 'h';
                    popup += ' <span style="color:#888;font-size:0.9em;">(' + posAgeStr + ' ago)</span>';
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
              
              // Add link to liamcottle meshview server
              popup += '<br><a href="https://meshtastic.liamcottle.net/?node_id=' + node.id + '" target="_blank" style="color:#2196F3;">View on Meshtastic Map</a>';
              
              // Add special packet info to popup
              if (node.is_special && node.id && specialPackets[node.id]){
                var pkts = specialPackets[node.id];
                var formatted = formatPacketInfo(pkts);
                if (formatted) {
                  popup += '<br><div style="margin-top:6px;padding-top:6px;border-top:1px solid #ccc;"><strong>Recent Packets:</strong><br><small>' + formatted + '</small></div>';
                }
              }
              
              var opts = { radius:8, color:'#222', weight:1, fillColor:color, fillOpacity:0.9 };
              if (!markers[key]){ 
                markers[key] = L.circleMarker([node.lat, node.lon], opts).addTo(map);
              } else { 
                markers[key].setLatLng([node.lat, node.lon]).setStyle(opts);
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
                  } else {
                    thresholdRing.setLatLng([originLat, originLon]);
                    thresholdRing.setRadius(threshold);
                    thresholdRing.setStyle(ringOpts);
                    // Update popup content
                    thresholdRing.bindPopup(popup);
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
              }
            }
            
            if (trailsEl && trailsEl.checked){
              for(var t=0; t<toMap.length; t++){
                var sn = toMap[t]; 
                if(!sn.is_special) continue;
                (function(node){
                  var hours = parseInt(hoursEl.value || '24', 10);
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
                        } 
                      } catch(e){ 
                        console.warn('trail parse error', e); 
                      }
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
          }
        } catch(e) {
          // Silent catch - don't let callback errors propagate
        }
      });
    } catch(e) {
      // Silent - don't let updateStatus errors break the poll loop
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
  };


  // initChannels removed: channel filter no longer used
  initMap(); 
  updateStatus(); // Call immediately to get initial status
  
  // Wrap initial fetch in try-catch to prevent blocking polling
  try {
    fetchSpecialPackets(function(){ 
      try {
        updateNodes(); 
      } catch(e) {
        console.error('[INIT] Error in updateNodes callback:', e);
      }
    }); 
  } catch(e) {
    console.error('[INIT] Error in fetchSpecialPackets:', e);
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
      var secondsRemaining = Math.max(0, Math.ceil((statusRefresh - timeSinceLastPoll) / 1000));
      
      // Update progress bar width
      var progressBar = document.getElementById('refresh-progress-bar');
      if (progressBar) {
        progressBar.style.width = Math.min(progress, 100) + '%';
      }
      
      // Update countdown text
      var countdownEl = document.getElementById('refresh-countdown');
      if (countdownEl) {
        if (isRateLimitPaused()) {
          var pauseRemaining = Math.max(0, Math.ceil((rateLimitPauseUntil - now) / 1000));
          countdownEl.textContent = '⏸️ ' + pauseRemaining;
          countdownEl.style.color = '#FF6F00';
        } else {
          countdownEl.textContent = secondsRemaining;
          countdownEl.style.color = '#666';
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
  
  // Start node polling immediately (after initial fetch)
  try {
    setInterval(function(){ 
      try {
        fetchSpecialPackets(function(){ updateNodes(); }); 
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
})();



