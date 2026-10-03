**Licences that go away:**
- Windows Server, for all server workloads (catalog web app, Web Forms catalog after the Blazor rewrite, WCF service) on Linux containers.
- SQL Server too, if Babelfish Compass confirms that Aurora PostgreSQL with Babelfish fits.

**Licences that stay:**
- SQL Server licence-included in RDS, if Babelfish does not fit;
- Windows on user desktops, which is not a server licence.

The code cannot price these. With the client's current licence counts (editions, cores, Software Assurance) and server utilisation, an **AWS Optimization and Licensing Assessment (OLA)** produces the cost comparison and right-sizing; the AWS Pricing Calculator models the target (Fargate tasks, RDS instance class, ALB). Funding programmes such as MAP are options for the AWS account team.
