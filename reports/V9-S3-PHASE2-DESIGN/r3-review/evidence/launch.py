import runpy, sys
stubs, runner = sys.argv[1], sys.argv[2]
sys.path.insert(0, stubs)
sys.argv = [runner] + sys.argv[3:]
runpy.run_path(runner, run_name="__main__")
