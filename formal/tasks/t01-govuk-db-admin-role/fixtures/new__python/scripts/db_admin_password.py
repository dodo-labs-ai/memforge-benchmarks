import subprocess, sys
role = "govuk-production-tempadmin"
print(subprocess.check_output(["gds", "aws", role, "--", "aws", "secretsmanager", "get-secret-value", "--secret-id", sys.argv[1]]))
