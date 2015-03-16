if (Meteor.isClient) {
  // This code only runs on the client
  Django = DDP.connect('http://localhost:8000/');
  Tasks = new Mongo.Collection("django_todos.task", {"connection": Django});
  Django.subscribe('django_todos.task');
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
