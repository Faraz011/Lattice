# Neo4j for Render: the pinned community image with APOC and GDS (KTD14). The wrapper builds
# NEO4J_AUTH from LATTICE_NEO4J_PASSWORD, so the database and the app roles share one generated
# secret from the blueprint's environment group.
FROM neo4j:2026.09.0-community

ENV NEO4J_PLUGINS='["apoc", "graph-data-science"]' \
    NEO4J_dbms_security_procedures_unrestricted="gds.*,apoc.*" \
    NEO4J_server_memory_heap_max__size=1G \
    NEO4J_server_memory_pagecache_size=512M \
    NEO4J_server_default__listen__address=0.0.0.0

COPY lattice-entrypoint.sh /startup/lattice-entrypoint.sh
RUN chmod +x /startup/lattice-entrypoint.sh

EXPOSE 7687 7474
ENTRYPOINT ["tini", "-g", "--", "/startup/lattice-entrypoint.sh"]
CMD ["neo4j"]
