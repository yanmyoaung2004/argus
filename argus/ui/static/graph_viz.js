(function () {
  "use strict";

  window.ArgusGraph = class ArgusGraph {
    constructor(containerId) {
      this.container = document.getElementById(containerId);
      if (!this.container) throw new Error("Container not found: " + containerId);
    }

    render(data) {
      var w = this.container.clientWidth;
      var h = this.container.clientHeight || 600;
      this.container.innerHTML = "";

      var nodes = data.nodes || [];
      var links = data.edges || [];

      var svg = d3.select(this.container)
        .append("svg")
        .attr("width", w)
        .attr("height", h)
        .attr("viewBox", [0, 0, w, h]);

      var g = svg.append("g");

      var zoom = d3.zoom()
        .scaleExtent([0.1, 6])
        .on("zoom", function (event) {
          g.attr("transform", event.transform);
        });
      svg.call(zoom);

      var simulation = d3.forceSimulation(nodes)
        .force("link", d3.forceLink(links).id(function (d) { return d.id; }).distance(120))
        .force("charge", d3.forceManyBody().strength(-400))
        .force("center", d3.forceCenter(w / 2, h / 2))
        .force("collision", d3.forceCollide(25));

      var linkEls = g.append("g")
        .selectAll("line")
        .data(links)
        .join("line")
        .attr("stroke", "#475569")
        .attr("stroke-opacity", 0.25)
        .attr("stroke-width", function (d) { return Math.max(0.5, (d.weight || 0.5) * 2); });

      var radii = { entity: 12, claim: 8, source: 5 };

      var nodeGroup = g.append("g").selectAll("g").data(nodes).join("g")
        .call(d3.drag()
          .on("start", function (event, d) {
            if (!event.active) simulation.alphaTarget(0.3).restart();
            d.fx = d.x;
            d.fy = d.y;
          })
          .on("drag", function (event, d) {
            d.fx = event.x;
            d.fy = event.y;
          })
          .on("end", function (event, d) {
            if (!event.active) simulation.alphaTarget(0);
            d.fx = null;
            d.fy = null;
          })
        )
        .on("click", function (event, d) {
          if (window.showNodeDetail) {
            event.stopPropagation();
            window.showNodeDetail(d.name, _buildNodeDetail(d));
          }
        });

      nodeGroup.append("circle")
        .attr("r", function (d) { return radii[d.type] || 7; })
        .attr("fill", function (d) { return _nodeColor(d); })
        .attr("stroke", "#1e293b")
        .attr("stroke-width", 1.5)
        .attr("cursor", "pointer");

      nodeGroup.append("title")
        .text(function (d) {
          return d.name + (d.confidence ? " (" + (d.confidence * 100).toFixed(0) + "%)" : "");
        });

      nodeGroup.filter(function (d) { return d.type === "entity"; })
        .append("text")
        .text(function (d) { return d.name; })
        .attr("font-size", 10)
        .attr("font-family", "Inter, -apple-system, sans-serif")
        .attr("fill", "#94a3b8")
        .attr("dx", function (d) { return (radii[d.type] || 7) + 5; })
        .attr("dy", 4)
        .attr("pointer-events", "none")
        .style("text-shadow", "0 0 4px #0a0f1a");

      simulation.on("tick", function () {
        linkEls
          .attr("x1", function (d) { return d.source.x; })
          .attr("y1", function (d) { return d.source.y; })
          .attr("x2", function (d) { return d.target.x; })
          .attr("y2", function (d) { return d.target.y; });
        nodeGroup.attr("transform", function (d) {
          return "translate(" + d.x + "," + d.y + ")";
        });
      });
    }
  };

  function _nodeColor(node) {
    if (node.type === "entity") return "#818cf8";
    if (node.type === "source") return "#64748b";
    var conf = node.confidence || 0.5;
    return conf >= 0.8 ? "#22c55e" : conf >= 0.5 ? "#eab308" : "#ef4444";
  }

  function _buildNodeDetail(node) {
    var html = '<div style="margin-bottom:0.5rem;"><strong>Type:</strong> ' + node.type + "</div>";
    if (node.confidence !== undefined) {
      html += '<div style="margin-bottom:0.5rem;"><strong>Confidence:</strong> ' + (node.confidence * 100).toFixed(0) + "%</div>";
    }
    return html;
  }
})();
