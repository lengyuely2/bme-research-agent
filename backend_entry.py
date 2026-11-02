from bioagent.desktop_service import main

if __name__ == "__main__":
    import sys
    if "--self-test" in sys.argv:
        import json
        from bioagent.selfcheck import run_checks
        result = run_checks()
        print(json.dumps(result))
        raise SystemExit(0 if result["passed"] else 1)
    main()
