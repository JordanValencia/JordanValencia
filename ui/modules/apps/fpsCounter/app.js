// Cheap FPS counter: reads the game's "stats" stream and only touches the DOM
// a couple of times per second.
angular.module('beamng.apps').directive('fpsCounter', ['StreamsManager', function (StreamsManager) {
  return {
    template: '<div style="font:bold 16px monospace;color:#0f0;background:rgba(0,0,0,.5);padding:2px 6px;border-radius:3px"></div>',
    replace: true,
    restrict: 'EA',
    link: function (scope, element) {
      var streams = ['stats'];
      var interval = 500; // ms between text updates
      var last = 0;
      var node = element[0];

      StreamsManager.add(streams);
      scope.$on('$destroy', function () { StreamsManager.remove(streams); });

      scope.$on('streamsUpdate', function (event, data) {
        var now = performance.now();
        if (now - last < interval) return;
        last = now;
        var fps = data.stats && data.stats.fps;
        node.textContent = fps != null ? Math.round(fps) + ' FPS' : '-- FPS';
      });
    }
  };
}]);
