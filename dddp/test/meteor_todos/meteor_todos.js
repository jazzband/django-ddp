if (Meteor.isClient) {
  // This code only runs on the client
  options = {};
  if (__meteor_runtime_config__.hasOwnProperty('DDP_DEFAULT_CONNECTION_URL')) {
    Django = Meteor;
  } else {
    Django = DDP.connect(window.location.protocol + '//'+window.location.hostname+':8000/');
    options.connection = Django;
  }
  Tasks = new Mongo.Collection("django_todos.task", options);
  TaskSub = Django.subscribe('Tasks');
  Template.body.helpers({
    tasks: function () {
      return Tasks.find({});
    }
  });
}

if (Meteor.isServer) {
  Meteor.startup(function () {
    // code to run on server at startup
  });
}
