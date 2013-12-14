"""
    SoftLayer.network
    ~~~~~~~~~~~~~~~~~
    Network Manager/helpers

    :copyright: (c) 2013, SoftLayer Technologies, Inc. All rights reserved.
    :license: MIT, see LICENSE for more details.
"""

from SoftLayer.utils import NestedDict, query_filter, resolve_ids, lookup


class NetworkManager(object):
    """ Manage Networks """
    def __init__(self, client):
        #: A valid `SoftLayer.API.Client` object that will be used for all
        #: actions.
        self.client = client
        #: Reference to the SoftLayer_Account API object.
        self.account = client['Account']
        #: Reference to the SoftLayer_Network_Vlan object.
        self.vlan = client['Network_Vlan']
        self.subnet = client['Network_Subnet']

    def add_global_ip(self, version=4, test_order=False):
        """ Adds a global IP address to the account.

        :param int version: Specifies whether this is IPv4 or IPv6
        :param bool test_order: If true, this will only verify the order.
        """
        # This method is here to improve the public interface from a user's
        # perspective since ordering a single global IP through the subnet
        # interface is not intuitive.
        return self.add_subnet('global', version=version,
                               test_order=test_order)

    def add_subnet(self, subnet_type, quantity=None, vlan_id=None, version=4,
                   test_order=False):
        package = self.client['Product_Package']
        category = 'sov_sec_ip_addresses_priv'
        desc = ''
        if version == 4:
            if subnet_type == 'global':
                quantity = 0
                category = 'global_ipv4'
            elif subnet_type == 'public':
                category = 'sov_sec_ip_addresses_pub'
        else:
            category = 'static_ipv6_addresses'
            if subnet_type == 'global':
                quantity = 0
                category = 'global_ipv6'
                desc = 'Global'
            elif subnet_type == 'public':
                desc = 'Portable'

        price_id = None
        quantity = str(quantity)
        # In the API, every non-server item is contained within package ID 0.
        # This means that we need to get all of the items and loop through them
        # looking for the items we need based upon the category, quantity, and
        # item description.
        for item in package.getItems(id=0, mask='itemCategory'):
            category_code = lookup(item, 'itemCategory', 'categoryCode')
            if all([category_code == category,
                    item.get('capacity') == quantity,
                    version == 4 or (version == 6 and
                                     desc in item['description'])]):
                price_id = item['prices'][0]['id']
                break

        order = {
            'packageId': 0,
            'prices': [{'id': price_id}],
            'quantity': 1,
        }

        if subnet_type != 'global':
            order['endPointVlanId'] = vlan_id

        if not price_id:
            raise TypeError('Invalid combination specified for ordering a'
                            ' subnet.')

        func = 'placeOrder'
        if test_order:
            func = 'verifyOrder'
        func = getattr(self.client['Product_Order'], func)

        # This is necessary in order for the XML-RPC endpoint to select the
        # correct order container. Without this, placing the order will fail.
        order['complexType'] = \
            'SoftLayer_Container_Product_Order_Network_Subnet'
        return func(order)

    def assign_global_ip(self, global_ip_id, target):
        """ Assigns a global IP address to a specified target.

        :param int global_ip_id: The ID of the global IP being assigned
        :param string target: The IP address to assign
        """
        return self.client['Network_Subnet_IpAddress_Global'].route(
            target, id=global_ip_id)

    def cancel_global_ip(self, global_ip_id):
        """ Cancels the specified global IP address.

        :param int id: The ID of the global IP to be cancelled.
        """
        service = self.client['Network_Subnet_IpAddress_Global']
        ip = service.getObject(id=global_ip_id, mask='billingItem')
        billing_id = ip['billingItem']['id']

        billing_item = self.client['Billing_Item']
        return billing_item.cancelService(id=billing_id)

    def cancel_subnet(self, subnet_id):
        """ Cancels the specified subnet.

        :param int subnet_id: The ID of the subnet to be cancelled.
        """
        subnet = self.get_subnet(subnet_id, mask='id, billingItem.id')
        billing_id = subnet['billingItem']['id']

        billing_item = self.client['Billing_Item']
        return billing_item.cancelService(id=billing_id)

    def edit_rwhois(self, abuse_email=None, address1=None, address2=None,
                    city=None, company_name=None, country=None,
                    first_name=None, last_name=None, postal_code=None,
                    private_residence=None, state=None):
        update = {}
        for key, value in [('abuseEmail', abuse_email),
                           ('address1', address1),
                           ('address2', address2),
                           ('city', city),
                           ('companyName', company_name),
                           ('country', country),
                           ('firstName', first_name),
                           ('lastName', last_name),
                           ('privateResidenceFlag', private_residence),
                           ('state', state),
                           ('postalCode', postal_code)]:
            if key is not None:
                update[key] = value

        # If there's anything to update, update it
        if update:
            rwhois = self.get_rwhois()
            self.client['Network_Subnet_Rwhois_Data'].editObject(
                update, id=rwhois['id'])

    def ip_lookup(self, ip):
        """ Looks up an IP address and returns network information about it.

        :param string ip: An IP address. Can be IPv4 or IPv6
        :returns: A dictionary of information about the IP

        """
        obj = self.client['Network_Subnet_IpAddress']
        return obj.getByIpAddress(ip, mask='hardware, virtualGuest')

    def get_rwhois(self):
        """ Returns the RWhois information about the current account.

        :returns: A dictionary containing the account's RWhois information.
        """
        return self.account.getRwhoisData()

    def get_subnet(self, subnet_id, **kwargs):
        """ Returns information about a single subnet.

        :param string id: Either the ID for the subnet or its network
                          identifier
        :returns: A dictionary of information about the subnet
        """
        if 'mask' not in kwargs:
            kwargs['mask'] = ','.join(self._get_subnet_mask())

        return self.subnet.getObject(id=subnet_id, **kwargs)

    def get_vlan(self, vlan_id):
        """ Returns information about a single VLAN.

        :param int id: The unique identifier for the VLAN
        :returns: A dictionary containing a large amount of information about
                  the specified VLAN.

        """
        return self.vlan.getObject(id=vlan_id, mask=self._get_vlan_mask())

    def list_global_ips(self, version=None, identifier=None, **kwargs):
        """ Returns a list of all global IP address records on the account.

        :param int version: Only returns IPs of this version (4 or 6)
        :param string identifier: If specified, the list will only contain the
                                  global ips matching this network identifier.
        """
        if 'mask' not in kwargs:
            mask = ['destinationIpAddress[hardware, virtualGuest]',
                    'ipAddress']
            kwargs['mask'] = ','.join(mask)

        _filter = NestedDict({})

        if version:
            v = query_filter(version)
            _filter['globalIpRecords']['ipAddress']['subnet']['version'] = v

        if identifier:
            subnet_filter = _filter['globalIpRecords']['ipAddress']['subnet']
            subnet_filter['networkIdentifier'] = query_filter(identifier)

        kwargs['filter'] = _filter.to_dict()
        return self.account.getGlobalIpRecords(**kwargs)

    def list_subnets(self, identifier=None, datacenter=None, version=0,
                     subnet_type=None, **kwargs):
        """ Display a list of all subnets on the account.

        This provides a quick overview of all subnets including information
        about data center residence and the number of devices attached.

        :param string identifier: If specified, the list will only contain the
                                    subnet matching this network identifier.
        :param string datacenter: If specified, the list will only contain
                                    subnets in the specified data center.
        :param int version: Only returns subnets of this version (4 or 6).
        :param string subnet_type: If specified, it will only returns subnets
                                     of this type.
        :param dict \*\*kwargs: response-level arguments (limit, offset, etc.)

        """
        if 'mask' not in kwargs:
            kwargs['mask'] = ','.join(self._get_subnet_mask())

        _filter = NestedDict(kwargs.get('filter') or {})

        if identifier:
            _filter['subnets']['networkIdentifier'] = query_filter(identifier)
        if datacenter:
            _filter['subnets']['datacenter']['name'] = \
                query_filter(datacenter)
        if version:
            _filter['subnets']['version'] = query_filter(version)
        if subnet_type:
            _filter['subnets']['subnetType'] = query_filter(subnet_type)
        else:
            # This filters out global IPs from the subnet listing.
            _filter['subnets']['subnetType'] = {'operation': '!= GLOBAL_IP'}

        kwargs['filter'] = _filter.to_dict()

        return self.account.getSubnets(**kwargs)

    def list_vlans(self, datacenter=None, vlan_number=None, vlan_name=None,
                   **kwargs):
        """ Display a list of all VLANs on the account.

        This provides a quick overview of all VLANs including information about
        data center residence and the number of devices attached.

        :param string datacenter: If specified, the list will only contain
                                    VLANs in the specified data center.
        :param int vlan_number: If specified, the list will only contain the
                                  VLAN matching this VLAN number.
        :param int vlan_name: If specified, the list will only contain the
                                  VLAN matching this VLAN name.
        :param dict \*\*kwargs: response-level arguments (limit, offset, etc.)

        """
        _filter = NestedDict(kwargs.get('filter') or {})

        if vlan_number:
            _filter['networkVlans']['vlanNumber'] = query_filter(vlan_number)

        if vlan_name:
            _filter['networkVlans']['name'] = query_filter(vlan_name)

        if datacenter:
            _filter['networkVlans']['primaryRouter']['datacenter']['name'] = \
                query_filter(datacenter)

        kwargs['filter'] = _filter.to_dict()

        if 'mask' not in kwargs:
            kwargs['mask'] = self._get_vlan_mask()

        return self.account.getNetworkVlans(**kwargs)

    def resolve_global_ip_ids(self, identifier):
        return resolve_ids(identifier, [self._list_global_ips_by_identifier])

    def resolve_subnet_ids(self, identifier):
        return resolve_ids(identifier, [self._list_subnets_by_identifier])

    def resolve_vlan_ids(self, identifier):
        return resolve_ids(identifier, [self._list_vlans_by_name])

    def summary_by_datacenter(self):
        """ Provides a dictionary with a summary of all network information on
        the account, grouped by data center.

        The resultant dictionary is primarily useful for statistical purposes.
        It contains count information rather than raw data. If you want raw
        information, see the :func:`list_vlans` method instead.

        :returns: A dictionary keyed by data center with the data containing a
                    series of counts for hardware, subnets, CCIs, and other
                    objects residing within that data center.

        """
        datacenters = {}
        unique_vms = []
        unique_servers = []
        unique_network = []

        for vlan in self.list_vlans():
            dc = vlan['primaryRouter']['datacenter']
            name = dc['name']
            if name not in datacenters:
                datacenters[name] = {
                    'hardwareCount': 0,
                    'networkingCount': 0,
                    'primaryIpCount': 0,
                    'subnetCount': 0,
                    'virtualGuestCount': 0,
                    'vlanCount': 0,
                }

            datacenters[name]['vlanCount'] += 1

            for hw in vlan['hardware']:
                if hw['id'] not in unique_servers:
                    datacenters[name]['hardwareCount'] += 1
                    unique_servers.append(hw['id'])

            for net in vlan['networkComponents']:
                if net['id'] not in unique_network:
                    datacenters[name]['networkingCount'] += 1
                    unique_network.append(net['id'])

            for vm in vlan['virtualGuests']:
                if vm['id'] not in unique_vms:
                    datacenters[name]['virtualGuestCount'] += 1
                    unique_vms.append(vm['id'])

            datacenters[name]['primaryIpCount'] += \
                vlan['totalPrimaryIpAddressCount']
            datacenters[name]['subnetCount'] += len(vlan['subnets'])

        return datacenters

    def unassign_global_ip(self, global_ip_id):
        """ Unassigns a global IP address from a target.

        :param int id: The ID of the global IP being unassigned
        """
        return self.client['Network_Subnet_IpAddress_Global'].unroute(
            id=global_ip_id)

    def _list_global_ips_by_identifier(self, identifier):
        """ Returns a list of IDs of the global IP matching the specified
            network identifier

        :param string identifier: The identifier to look up
        :returns: The ID of the matching subnet or None
        """
        results = self.list_global_ips(identifier=identifier, mask='id')
        return [result['id'] for result in results]

    def _list_subnets_by_identifier(self, identifier):
        """ Returns a list of IDs of the subnet matching the specified
            network identifier

        :param string identifier: The identifier to look up
        :returns: The ID of the matching subnet or None
        """
        identifier = identifier.split('/', 1)[0]

        results = self.list_subnets(identifier=identifier, mask='id')
        return [result['id'] for result in results]

    def _list_vlans_by_name(self, name):
        results = self.list_vlans(vlan_name=name, mask='id')
        return [result['id'] for result in results]

    def _get_subnet_mask(self):
        """ Returns the standard subnet object mask.

        Wrapper method to prevent duplicated code.

        """
        return [
            'hardware',
            'datacenter',
            'ipAddressCount',
            'virtualGuests',
        ]

    def _get_vlan_mask(self):
        """ Returns the standard VLAN object mask.

        Wrapper method for preventing duplicated code.

        """
        mask = [
            'firewallInterfaces',
            'hardware',
            'networkComponents',
            'primaryRouter[id, fullyQualifiedDomainName, datacenter]',
            'subnets',
            'totalPrimaryIpAddressCount',
            'virtualGuests',
        ]

        return ','.join(mask)
