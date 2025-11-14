/* Buoy Tracker Client Script (ES5) */
(function(){
  var APP_JS_VERSION = 'v3';
  console.log('Buoy Tracker client script loaded', APP_JS_VERSION);
  var map = null;
  var markers = {};
  var trails = {};
  var movementCircles = {}; // origin-anchored movement alert circles per node
  var thresholdRings = {}; // threshold rings around home positions for special nodes
  var movementLines = {}; // red lines from origin to current position when moved
  var movedAlertShown = {}; // track one-time alerts per node id
  var specialPackets = {}; // cache of special node packets
  var voltageGraphCache = {}; // pre-rendered voltage graphs HTML for special nodes
  var availableChannels = []; // list of all channels (from config + discovered)
  var activeChannels = {}; // channel filter state {channelName: true/false}
  
  var specialOnlyEl = document.getElementById('filter-special-only');
  var offlineEl = document.getElementById('toggle-offline-specials');
  var trailsEl = document.getElementById('toggle-trails');
  var hoursEl = document.getElementById('trail-hours');
  var sortByEl = document.getElementById('sort-by');
  
  // Initialize channels from config
  function initChannels(){
    var d = document.body.dataset;
    var configChannels = d.mqttChannels || '';
    if (configChannels) {
      var channelList = configChannels.split(',');
      for (var i = 0; i < channelList.length; i++) {
        var ch = channelList[i].trim();
        if (ch) {
          availableChannels.push(ch);
          activeChannels[ch] = true; // Enable all by default
        }
      }
    }
    console.log('Initialized channels from config:', availableChannels);
  }
  
  if (offlineEl) offlineEl.checked = true;
  function attachChange(el){ if(el && el.addEventListener){ el.addEventListener('change', function(){ updateNodes(); }); } }
  attachChange(specialOnlyEl); attachChange(offlineEl); attachChange(trailsEl); attachChange(sortByEl);
  
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

  function updateChannelFilter(){
    var container = document.getElementById('channel-filter');
    if (!container) return;
    
    // Build list of channel chips
    var html = '';
    for (var i = 0; i < availableChannels.length; i++) {
      var ch = availableChannels[i];
      var isActive = activeChannels[ch] !== false; // default to true
      var className = 'channel-chip' + (isActive ? ' active' : '');
      html += '<div class="' + className + '" onclick="toggleChannel(\'' + ch + '\')">' + ch + '</div>';
    }
    container.innerHTML = html;
  }

  window.toggleChannel = function(channelName){
    activeChannels[channelName] = !activeChannels[channelName];
    updateChannelFilter();
    updateNodes();
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

  // Generate inline SVG voltage graph from data points
  function generateVoltageGraph(voltageData) {
    if (!voltageData || voltageData.length < 2) {
      return ''; // Need at least 2 points for a graph
    }
    
    var width = 240;  // Reduced from 280
    var height = 60;  // Reduced from 80
    var padding = { top: 8, right: 8, bottom: 15, left: 30 };  // Reduced padding
    var graphWidth = width - padding.left - padding.right;
    var graphHeight = height - padding.top - padding.bottom;
    
    // Find min/max voltage for Y-axis
    var minVoltage = 3.0; // LiPo minimum
    var maxVoltage = 4.2; // LiPo maximum
    for (var i = 0; i < voltageData.length; i++) {
      var v = voltageData[i].voltage;
      if (v < minVoltage) minVoltage = Math.floor(v * 10) / 10;
      if (v > maxVoltage) maxVoltage = Math.ceil(v * 10) / 10;
    }
    
    // Time range
    var minTime = voltageData[0].timestamp;
    var maxTime = voltageData[voltageData.length - 1].timestamp;
    var timeRange = maxTime - minTime;
    
    // Scale functions
    function scaleX(timestamp) {
      return padding.left + ((timestamp - minTime) / timeRange) * graphWidth;
    }
    function scaleY(voltage) {
      return padding.top + graphHeight - ((voltage - minVoltage) / (maxVoltage - minVoltage)) * graphHeight;
    }
    
    // Build SVG path
    var pathData = 'M';
    for (var i = 0; i < voltageData.length; i++) {
      var x = scaleX(voltageData[i].timestamp);
      var y = scaleY(voltageData[i].voltage);
      pathData += (i === 0 ? '' : ' L') + x.toFixed(1) + ',' + y.toFixed(1);
    }
    
    // Format time labels
    function formatTimeLabel(timestamp) {
      var d = new Date(timestamp * 1000);
      return (d.getMonth() + 1) + '/' + d.getDate();
    }
    
    var startLabel = formatTimeLabel(minTime);
    var endLabel = formatTimeLabel(maxTime);
    
    // Generate SVG
    var svg = '<svg width="' + width + '" height="' + height + '" style="background:#f9f9f9;border:1px solid #ddd;border-radius:3px;">';
    
    // Grid lines (horizontal)
    svg += '<line x1="' + padding.left + '" y1="' + scaleY(4.2) + '" x2="' + (width - padding.right) + '" y2="' + scaleY(4.2) + '" stroke="#ddd" stroke-width="1" stroke-dasharray="2,2"/>';
    svg += '<line x1="' + padding.left + '" y1="' + scaleY(3.0) + '" x2="' + (width - padding.right) + '" y2="' + scaleY(3.0) + '" stroke="#ddd" stroke-width="1" stroke-dasharray="2,2"/>';
    
    // Voltage line
    svg += '<path d="' + pathData + '" fill="none" stroke="#2196F3" stroke-width="2"/>';
    
    // Data points
    for (var i = 0; i < voltageData.length; i++) {
      var x = scaleX(voltageData[i].timestamp);
      var y = scaleY(voltageData[i].voltage);
      svg += '<circle cx="' + x.toFixed(1) + '" cy="' + y.toFixed(1) + '" r="2" fill="#2196F3"/>';  // Smaller dots
    }
    
    // Y-axis labels (smaller font)
    svg += '<text x="3" y="' + (scaleY(4.2) + 3) + '" font-size="8" fill="#666">4.2V</text>';
    svg += '<text x="3" y="' + (scaleY(3.0) + 3) + '" font-size="8" fill="#666">3.0V</text>';
    
    // X-axis labels (smaller font)
    svg += '<text x="' + padding.left + '" y="' + (height - 3) + '" font-size="8" fill="#666">' + startLabel + '</text>';
    svg += '<text x="' + (width - padding.right - 20) + '" y="' + (height - 3) + '" font-size="8" fill="#666">' + endLabel + '</text>';
    
    svg += '</svg>';
    
    return svg;
  }

  // Function to fetch and cache voltage graphs for special nodes
  function updateVoltageGraphs() {
    fetch('/api/nodes')
      .then(function(response) { return response.json(); })
      .then(function(data) {
        var nodes = data.nodes || [];
        nodes.forEach(function(node) {
          if (node.is_special && node.id && node.voltage != null) {
            // Fetch voltage history for this special node
            fetch('/api/special/voltage_history/' + node.id + '?days=7')
              .then(function(response) { return response.json(); })
              .then(function(voltageData) {
                if (voltageData.data && voltageData.data.length >= 2) {
                  // Generate graph and cache it
                  var graph = generateVoltageGraph(voltageData.data);
                  voltageGraphCache[node.id] = '<div style="margin-top:8px;padding:8px;background:#f8f9fa;border-radius:4px;">' +
                    '<div style="font-size:0.85em;font-weight:bold;margin-bottom:4px;">Battery Voltage (Past Week)</div>' +
                    graph + '</div>';
                } else if (voltageData.data && voltageData.data.length === 1) {
                  voltageGraphCache[node.id] = '<div style="margin-top:8px;padding:8px;background:#f8f9fa;border-radius:4px;">' +
                    '<div style="font-size:0.85em;font-weight:bold;margin-bottom:4px;">Battery Voltage</div>' +
                    '<div style="text-align:center;padding:10px;color:#999;font-size:0.8em;">Only one data point available</div></div>';
                } else {
                  voltageGraphCache[node.id] = '<div style="margin-top:8px;padding:8px;background:#f8f9fa;border-radius:4px;">' +
                    '<div style="font-size:0.85em;font-weight:bold;margin-bottom:4px;">Battery Voltage</div>' +
                    '<div style="text-align:center;padding:10px;color:#999;font-size:0.8em;">No voltage history available</div></div>';
                }
              })
              .catch(function(err) {
                console.error('Failed to load voltage history for node', node.id, ':', err);
              });
          }
        });
      })
      .catch(function(err) {
        console.error('Failed to fetch nodes for voltage graph update:', err);
      });
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
    
    // Compact header: name + status on one line
    var header = '<div class="node-name">';
    header += displayName;
    if (node.stale || node.status === 'gray') { 
      header += ' <span style="color:#a00;font-size:0.8em">(no GPS data received)</span>'; 
    }
    header += '</div>';
    
    var info = '';
    if (node.has_fix){
      var bat = (node.battery != null) ? node.battery : '?';
      var voltage = (node.voltage != null) ? node.voltage.toFixed(2) + 'V' : '';
      var channel = node.channel_name ? node.channel_name : (node.modem_preset ? node.modem_preset : '');
      
      // Build battery display with voltage and percentage
      var batteryDisplay = '';
      var batteryTooltip = 'Battery voltage and charge level';
      if (voltage && bat !== '?') {
        batteryDisplay = voltage + ' (' + bat + '%)';
        batteryTooltip = 'Battery: ' + voltage + ' at ' + bat + '% charge';
      } else if (voltage) {
        batteryDisplay = voltage;
        batteryTooltip = 'Battery voltage: ' + voltage;
      } else if (bat !== '?') {
        batteryDisplay = 'Bat: ' + bat + '%';
        batteryTooltip = 'Battery charge level: ' + bat + '%';
      }
      
      // Add low battery indicator
      if (node.battery_low) {
        batteryDisplay += ' ⚠️';
        batteryTooltip += ' (LOW BATTERY WARNING)';
      }
      
      // Build info line with tooltips: Channel | Battery display
      var infoParts = [];
      if (channel) {
        infoParts.push('<span class="tooltip-item">' + channel + '<span class="tooltip-balloon">LoRa channel/modem preset</span></span>');
      }
      if (batteryDisplay) {
        infoParts.push('<span class="tooltip-item">' + batteryDisplay + '<span class="tooltip-balloon">' + batteryTooltip + '</span></span>');
      }
      info = infoParts.join(' | ');
      
      // Build LPU, SoL, and Moved on single line with tooltips
      var now = Date.now() / 1000;
      var statusParts = [];
      
      // LPU: Time since last position update
      if (node.last_position_update != null) {
        var lpuAge = Math.round(now - node.last_position_update);
        var lpuStr = '';
        if (lpuAge < 60) lpuStr = lpuAge + 's';
        else if (lpuAge < 3600) lpuStr = Math.floor(lpuAge / 60) + 'm';
        else lpuStr = Math.floor(lpuAge / 3600) + 'h';
        statusParts.push('<span class="tooltip-item">LPU: ' + lpuStr + '<span class="tooltip-balloon">Last Position Update: Time since last GPS position packet</span></span>');
      } else {
        statusParts.push('<span class="tooltip-item">LPU: ?<span class="tooltip-balloon">Last Position Update: No position data yet</span></span>');
      }
      
      // SoL: Time since any packet received (last_seen)
      if (node.last_seen != null) {
        var solAge = Math.round(now - node.last_seen);
        var solStr = '';
        if (solAge < 60) solStr = solAge + 's';
        else if (solAge < 3600) solStr = Math.floor(solAge / 60) + 'm';
        else solStr = Math.floor(solAge / 3600) + 'h';
        statusParts.push('<span class="tooltip-item">SoL: ' + solStr + '<span class="tooltip-balloon">Sign of Life: Time since any packet received</span></span>');
      } else {
        statusParts.push('<span class="tooltip-item">SoL: ?<span class="tooltip-balloon">Sign of Life: No packets received yet</span></span>');
      }
      
      // Moved: Distance from origin for special nodes
      if (node.is_special && node.distance_from_origin_m != null && node.origin_lat != null && node.origin_lon != null){
        var distm = Math.round(Number(node.distance_from_origin_m));
        if (!isNaN(distm)){
          statusParts.push('<span class="tooltip-item">Moved: ' + distm + 'M<span class="tooltip-balloon">Distance moved from home position</span></span>');
        }
      }
      
      // Combine all status parts on single line
      if (statusParts.length > 0) {
        info += '<br><small>' + statusParts.join(' | ') + '</small>';
      }
    } else {
      // For nodes without GPS fix, just show channel if available
      var channel2 = node.channel_name ? node.channel_name : (node.modem_preset ? node.modem_preset : '');
      if (channel2) info = channel2;
    }
    
    // Add extra packet info for special nodes - REMOVED to keep cards compact
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
      var xhr = new XMLHttpRequest();
      xhr.open('GET', '/api/special/packets?limit=10', true);
      xhr.onreadystatechange = function(){
        if (xhr.readyState === 4){
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
        }
      };
      xhr.send();
    } catch(e){ 
      console.error('Failed to fetch special packets', e); 
      if (callback) callback(); // Call callback even on error
    }
  }

  function updateNodes(){
    try {
      var xhr = new XMLHttpRequest();
      // Add cache-busting parameter to prevent browser caching
      var cacheBuster = '?_=' + Date.now();
      xhr.open('GET', '/api/nodes' + cacheBuster, true);
      xhr.onreadystatechange = function(){
        if (xhr.readyState === 4){
          if (xhr.status !== 200){ console.warn('nodes request failed', xhr.status); return; }
          var data; try { data = JSON.parse(xhr.responseText); } catch(e){ console.warn('bad json', e); return; }
          if (!data || !data.nodes || !data.nodes.length){ 
            document.getElementById('nodes').innerHTML=''; 
            document.getElementById('node-count').textContent='0'; 
            return; 
          }
          
          // Merge discovered channels with configured channels
          var discoveredChannels = {};
          for (var i = 0; i < data.nodes.length; i++) {
            var n = data.nodes[i];
            if (n.channel_name) discoveredChannels[n.channel_name] = true;
          }
          
          // Add any newly discovered channels to availableChannels
          for (var discCh in discoveredChannels) {
            if (discoveredChannels.hasOwnProperty(discCh)) {
              var found = false;
              for (var j = 0; j < availableChannels.length; j++) {
                if (availableChannels[j] === discCh) {
                  found = true;
                  break;
                }
              }
              if (!found) {
                availableChannels.push(discCh);
                activeChannels[discCh] = true; // Enable newly discovered channels
              }
            }
          }
          availableChannels.sort();
          updateChannelFilter();
          
          var list = data.nodes.slice(0);
          
          // Apply channel filter
          var filtered = [];
          for (var k = 0; k < list.length; k++) {
            var node = list[k];
            var channelName = node.channel_name || 'Unknown';
            if (activeChannels[channelName] !== false) {
              filtered.push(node);
            }
          }
          list = filtered;
          
          if (specialOnlyEl && specialOnlyEl.checked){ 
            var tmp = []; 
            for(var m=0;m<list.length;m++){ 
              if(list[m].is_special) tmp.push(list[m]); 
            } 
            list = tmp; 
          }
          
          if (offlineEl && !offlineEl.checked){ 
            var tmp2 = []; 
            for(var p=0;p<list.length;p++){ 
              if(list[p].has_fix) tmp2.push(list[p]); 
            } 
            list = tmp2; 
          }
          
          var sortMode = sortByEl ? sortByEl.value : 'name';
          list.sort(function(a, b){
            if(a.is_special && !b.is_special) return -1;
            if(!a.is_special && b.is_special) return 1;
            if(sortMode === 'name'){
              var nameA = (a.name || 'Unknown').toLowerCase();
              var nameB = (b.name || 'Unknown').toLowerCase();
              if(nameA < nameB) return -1;
              if(nameA > nameB) return 1;
              return 0;
            } else if(sortMode === 'seen-newest'){
              var timeA = a.time_since_seen || 999999;
              var timeB = b.time_since_seen || 999999;
              return timeA - timeB;
            } else if(sortMode === 'seen-oldest'){
              var timeA2 = a.time_since_seen || 999999;
              var timeB2 = b.time_since_seen || 999999;
              return timeB2 - timeA2;
            }
            return 0;
          });
          
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
              
              if (node.is_special){ 
                if (node.status === 'gray'){
                  // No position fix yet - show at home position in gray
                  color = '#999999';
                } else if (node.stale){ 
                  color = '#888888'; 
                } else { 
                  color = '#FFD700'; 
                } 
              } else if (node.status === 'blue'){ 
                color = '#2196F3'; 
              } else if (node.status === 'orange'){ 
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
              if (node.voltage != null) {
                popup += '<br>Battery: ' + node.voltage.toFixed(2) + 'V (' + bat2 + '%)';
                if (node.battery_low) {
                  popup += ' ⚠️ LOW';
                }
                
                // Add pre-rendered voltage graph from cache for special nodes
                if (node.is_special && node.id && voltageGraphCache[node.id]) {
                  popup += voltageGraphCache[node.id];
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
                if (node.power_current != null) {
                  popup += '<br>Power: ' + node.power_current.toFixed(2) + 'A';
                }
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
                // Debug log for special nodes
                if (node.is_special) {
                  console.log('Created marker for ' + nm2 + ' at', node.lat, node.lon);
                }
              } else { 
                markers[key].setLatLng([node.lat, node.lon]).setStyle(opts);
                // Debug log for special nodes 
                if (node.is_special) {
                  console.log('Updated marker for ' + nm2 + ' to', node.lat, node.lon);
                }
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
                  var xhr2 = new XMLHttpRequest();
                  xhr2.open('GET', '/api/special/history?node_id=' + node.id + '&hours=' + hours, true);
                  xhr2.onreadystatechange = function(){
                    if (xhr2.readyState === 4 && xhr2.status === 200){
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
                  }; 
                  xhr2.send();
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
        }
      }; 
      xhr.send();
    } catch(e){ console.error('Update error:', e); }
  }

  function updateStatus(){
    try { 
      var xhr = new XMLHttpRequest(); 
      xhr.open('GET', '/api/status', true); 
      xhr.onreadystatechange = function(){ 
        if (xhr.readyState === 4){ 
          if (xhr.status !== 200){ 
            document.getElementById('mqtt-status').textContent = '⚠️ Error'; 
            return; 
          } 
          try { 
            var data2 = JSON.parse(xhr.responseText); 
            var txt = (data2 && data2.mqtt_connected)? '✅ Connected':'❌ Disconnected'; 
            document.getElementById('mqtt-status').textContent = txt; 
          } catch(e){ 
            document.getElementById('mqtt-status').textContent = '⚠️ Error'; 
          } 
        } 
      }; 
      xhr.send(); 
    } catch(e){ 
      document.getElementById('mqtt-status').textContent = '⚠️ Error'; 
    }
  }

  window.showRecent = function(){
    try { 
      var xhr = new XMLHttpRequest(); 
      xhr.open('GET', '/api/recent_messages', true); 
      xhr.onreadystatechange = function(){ 
        if (xhr.readyState === 4){ 
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
        } 
      }; 
      xhr.send(); 
    } catch(e){ 
      alert('Error fetching recent messages'); 
    }
  };
  
  window.centerNode = function(lat, lon){ 
    if (map) map.setView([lat, lon], 13); 
  };

  window.reloadConfig = function(){
    if (!confirm('Reload configuration from tracker.config?\n\nThis will update special nodes and other settings without restarting the server.')) {
      return;
    }
    try {
      var xhr = new XMLHttpRequest();
      xhr.open('POST', '/api/config/reload', true);
      xhr.onreadystatechange = function(){
        if (xhr.readyState === 4){
          if (xhr.status === 200){
            try {
              var data = JSON.parse(xhr.responseText);
              alert('Configuration reloaded!\n\n' + data.message + '\nSpecial nodes: ' + data.special_nodes);
              // Refresh the page to show updated data
              setTimeout(function(){ window.location.reload(); }, 1000);
            } catch(e){
              alert('Configuration reloaded, but response parsing failed');
            }
          } else {
            alert('Failed to reload configuration. Check server logs.');
          }
        }
      };
      xhr.send();
    } catch(e){
      alert('Error reloading configuration: ' + e.message);
    }
  };

  window.restartServer = function(){
    if (!confirm('Restart the server?\n\nThe server will restart in 2 seconds. The page will reload automatically.')) {
      return;
    }
    try {
      var xhr = new XMLHttpRequest();
      xhr.open('POST', '/api/restart', true);
      xhr.onreadystatechange = function(){
        if (xhr.readyState === 4){
          if (xhr.status === 200){
            alert('Server is restarting...\n\nThe page will reload in 5 seconds.');
            setTimeout(function(){ window.location.reload(); }, 5000);
          } else {
            alert('Restart request may have failed. Check if server is running.');
          }
        }
      };
      xhr.send();
    } catch(e){
      alert('Error restarting server: ' + e.message);
    }
  };

  initChannels(); // Initialize channels from config
  initMap(); 
  updateStatus(); 
  fetchSpecialPackets(function(){ updateNodes(); }); // Fetch special packets first, then update nodes
  updateVoltageGraphs(); // Initial fetch of voltage graphs for special nodes
  
  var statusRefresh = parseInt(document.body.dataset.statusRefresh || '5000', 10);
  var nodeRefresh = parseInt(document.body.dataset.nodeRefresh || '5000', 10);
  setInterval(updateStatus, statusRefresh);
  setInterval(function(){ fetchSpecialPackets(function(){ updateNodes(); }); }, nodeRefresh);
  setInterval(updateVoltageGraphs, 60000); // Update voltage graphs every 60 seconds
})();



