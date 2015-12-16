var exec = require('child_process').exec;
var gulp = require('gulp');
var browserSync = require('browser-sync');

gulp.task('sphinx', function(cb) {
	exec('make html', function(err, stdout, stderr) {
		console.log(stdout);
		console.log(stderr);
		cb(err);
		browserSync.reload();
	});
});

gulp.task('default', ['sphinx'], function() {
	browserSync({
		open: false,
		server: {
			baseDir: '_build/html/'
		}
	});
	gulp.watch(["../README.rst", "../LICENSE", "../CHANGES.rst", "**/*.rst", "_static/**", "conf.py"], ['sphinx']);
});
